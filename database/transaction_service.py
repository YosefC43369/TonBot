"""
Transaction history service.

Fetches events from TonAPI, normalizes them, and stores them with
deduplication via provider_event_id.

Does NOT mark events as confirmed unless provider signals in_progress=False.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from database.repositories import CursorRepository, TransactionRepository
from ton.address import parse_address
from ton.base_client import AccountNotFoundError
from ton.schemas import Transaction
from ton.tonapi_client import TonApiClient

_PROVIDER_ID = "tonapi"


@dataclass(frozen=True)
class TransactionSummary:
    event_id: str
    timestamp: datetime | None
    action_type: str | None
    status: str
    is_scam: bool
    in_progress: bool


@dataclass
class TransactionHistoryResult:
    canonical_address: str
    transactions: list[TransactionSummary] = field(default_factory=list)
    next_cursor: int | None = None   # before_lt value for next page
    total_fetched: int = 0


def _normalize_status(tx: Transaction) -> str:
    if tx.in_progress:
        return "pending"
    return "confirmed"


def _extract_action_type(tx: Transaction) -> str | None:
    """Best-effort: pull the first action's type string."""
    if tx.actions:
        first = tx.actions[0]
        if isinstance(first, dict):
            return first.get("type")
    return None


class TransactionService:
    def __init__(
        self,
        session: AsyncSession,
        ton_client: TonApiClient,
    ) -> None:
        self._session = session
        self._client = ton_client
        self._tx_repo = TransactionRepository(session)
        self._cursor_repo = CursorRepository(session)

    async def get_history(
        self,
        raw_address: str,
        limit: int = 20,
        before_lt: int | None = None,
    ) -> TransactionHistoryResult:
        """
        Fetch transaction history from TonAPI, persist new events,
        and return a summary.

        Pagination: pass next_cursor from a previous result as before_lt.
        Events with in_progress=True are marked "pending" — not confirmed.
        """
        addr = parse_address(raw_address)
        result = TransactionHistoryResult(canonical_address=addr.canonical)

        try:
            page = await self._client.get_events(
                addr.canonical,
                limit=limit,
                before_lt=before_lt,
            )
        except AccountNotFoundError:
            return result

        summaries: list[TransactionSummary] = []
        for tx in page.events:
            status = _normalize_status(tx)
            action_type = _extract_action_type(tx)

            ts: datetime | None = None
            if tx.timestamp:
                ts = datetime.fromtimestamp(tx.timestamp, tz=timezone.utc)

            # Minimal metadata for reconciliation — no full raw dump
            metadata = {
                "lt": tx.lt,
                "fee_total": tx.fees.get("total"),
                "action_count": len(tx.actions),
            }

            await self._tx_repo.upsert(
                canonical_address=addr.canonical,
                provider_event_id=tx.event_id,
                tx_timestamp=ts,
                raw_action_type=action_type,
                status=status,
                source_metadata=metadata,
            )

            summaries.append(
                TransactionSummary(
                    event_id=tx.event_id,
                    timestamp=ts,
                    action_type=action_type,
                    status=status,
                    is_scam=tx.is_scam,
                    in_progress=tx.in_progress,
                )
            )

        result.transactions = summaries
        result.next_cursor = page.next_from
        result.total_fetched = len(summaries)
        return result

    async def fetch_and_store_new(
        self,
        canonical_address: str,
    ) -> list[str]:
        """
        Fetch only events newer than the stored cursor.
        Returns a list of new provider_event_ids.
        Used by the background worker.
        """
        cursor_str = await self._cursor_repo.get(_PROVIDER_ID, canonical_address)
        before_lt = int(cursor_str) if cursor_str else None

        new_ids: list[str] = []

        # Fetch up to one page of new events
        page = await self._client.get_events(
            canonical_address,
            limit=100,
            before_lt=before_lt,
        )

        for tx in page.events:
            already_seen = await self._tx_repo.has_event(tx.event_id)
            if already_seen:
                continue

            status = _normalize_status(tx)
            action_type = _extract_action_type(tx)
            ts = (
                datetime.fromtimestamp(tx.timestamp, tz=timezone.utc)
                if tx.timestamp
                else None
            )
            metadata = {
                "lt": tx.lt,
                "action_count": len(tx.actions),
            }

            _, created = await self._tx_repo.upsert(
                canonical_address=canonical_address,
                provider_event_id=tx.event_id,
                tx_timestamp=ts,
                raw_action_type=action_type,
                status=status,
                source_metadata=metadata,
            )
            if created:
                new_ids.append(tx.event_id)

        # Update cursor to the most recent logical time seen
        if page.events and page.next_from is not None:
            await self._cursor_repo.save(
                _PROVIDER_ID, canonical_address, str(page.next_from)
            )

        return new_ids