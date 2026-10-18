"""
Repository layer — all SQL access goes through here.

No SQL appears in handlers or services.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AuditLog, ProviderCursor, TransactionRecord, User, WatchlistEntry


# ── Users ─────────────────────────────────────────────────────────────────────


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_or_create(self, telegram_id: int) -> tuple[User, bool]:
        """
        Return the User for this telegram_id, creating it if absent.
        Returns (user, created).
        """
        result = await self._s.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user:
            return user, False
        user = User(telegram_id=telegram_id)
        self._s.add(user)
        await self._s.flush()
        return user, True

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self._s.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


# ── Watchlist ─────────────────────────────────────────────────────────────────


class WatchlistRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def count_for_user(self, user_id: int) -> int:
        from sqlalchemy import func

        result = await self._s.execute(
            select(func.count()).select_from(WatchlistEntry).where(
                WatchlistEntry.user_id == user_id,
                WatchlistEntry.is_active.is_(True),
            )
        )
        return result.scalar_one()

    async def add(
        self,
        user_id: int,
        canonical_address: str,
        label: str | None = None,
    ) -> WatchlistEntry | None:
        """
        Add a watchlist entry. Returns None if the entry already exists
        (duplicate prevention via unique constraint).
        """
        entry = WatchlistEntry(
            user_id=user_id,
            canonical_address=canonical_address,
            label=label,
            is_active=True,
        )
        self._s.add(entry)
        try:
            await self._s.flush()
        except IntegrityError:
            await self._s.rollback()
            return None
        return entry

    async def remove(self, user_id: int, canonical_address: str) -> bool:
        """
        Soft-delete a watchlist entry for this user.
        Returns True if an active entry was found and deactivated.
        """
        result = await self._s.execute(
            update(WatchlistEntry)
            .where(
                WatchlistEntry.user_id == user_id,
                WatchlistEntry.canonical_address == canonical_address,
                WatchlistEntry.is_active.is_(True),
            )
            .values(is_active=False)
        )
        return result.rowcount > 0  # type: ignore[return-value]

    async def list_for_user(self, user_id: int) -> list[WatchlistEntry]:
        result = await self._s.execute(
            select(WatchlistEntry)
            .where(
                WatchlistEntry.user_id == user_id,
                WatchlistEntry.is_active.is_(True),
            )
            .order_by(WatchlistEntry.created_at)
        )
        return list(result.scalars().all())

    async def get(self, user_id: int, canonical_address: str) -> WatchlistEntry | None:
        result = await self._s.execute(
            select(WatchlistEntry).where(
                WatchlistEntry.user_id == user_id,
                WatchlistEntry.canonical_address == canonical_address,
                WatchlistEntry.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def all_active_addresses(self) -> list[str]:
        """Return distinct canonical addresses currently on any active watchlist."""
        from sqlalchemy import distinct

        result = await self._s.execute(
            select(distinct(WatchlistEntry.canonical_address)).where(
                WatchlistEntry.is_active.is_(True)
            )
        )
        return list(result.scalars().all())


# ── Transactions ──────────────────────────────────────────────────────────────


class TransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert(
        self,
        canonical_address: str,
        provider_event_id: str,
        tx_timestamp: datetime | None,
        raw_action_type: str | None,
        status: str,
        source_metadata: dict | None = None,
    ) -> tuple[TransactionRecord, bool]:
        """
        Insert if not seen before (idempotent on provider_event_id).
        Returns (record, created).
        source_metadata is stored as compact JSON — no raw provider dumps.
        """
        meta_str = json.dumps(source_metadata, separators=(",", ":")) if source_metadata else None

        stmt = (
            pg_insert(TransactionRecord)
            .values(
                canonical_address=canonical_address,
                provider_event_id=provider_event_id,
                tx_timestamp=tx_timestamp,
                raw_action_type=raw_action_type,
                status=status,
                source_metadata=meta_str,
            )
            .on_conflict_do_nothing(constraint="uq_transactions_provider_event_id")
            .returning(TransactionRecord)
        )
        result = await self._s.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            return row, True
        # Already existed — fetch it
        existing = await self._s.execute(
            select(TransactionRecord).where(
                TransactionRecord.provider_event_id == provider_event_id
            )
        )
        return existing.scalar_one(), False

    async def list_for_address(
        self,
        canonical_address: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[TransactionRecord]:
        result = await self._s.execute(
            select(TransactionRecord)
            .where(TransactionRecord.canonical_address == canonical_address)
            .order_by(TransactionRecord.tx_timestamp.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def has_event(self, provider_event_id: str) -> bool:
        result = await self._s.execute(
            select(TransactionRecord.id).where(
                TransactionRecord.provider_event_id == provider_event_id
            )
        )
        return result.scalar_one_or_none() is not None


# ── Provider cursors ──────────────────────────────────────────────────────────


class CursorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, provider_id: str, canonical_address: str) -> str | None:
        result = await self._s.execute(
            select(ProviderCursor.cursor_value).where(
                ProviderCursor.provider_id == provider_id,
                ProviderCursor.canonical_address == canonical_address,
            )
        )
        return result.scalar_one_or_none()

    async def save(
        self, provider_id: str, canonical_address: str, cursor_value: str | None
    ) -> None:
        stmt = (
            pg_insert(ProviderCursor)
            .values(
                provider_id=provider_id,
                canonical_address=canonical_address,
                cursor_value=cursor_value,
                updated_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_update(
                constraint="uq_cursor_provider_address",
                set_={
                    "cursor_value": cursor_value,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
        )
        await self._s.execute(stmt)


# ── Audit log ─────────────────────────────────────────────────────────────────


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def record(
        self,
        action: str,
        actor_telegram_id: int | None = None,
        resource_ref: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        meta_str = json.dumps(metadata, separators=(",", ":")) if metadata else None
        entry = AuditLog(
            actor_telegram_id=actor_telegram_id,
            action=action,
            resource_ref=resource_ref,
            metadata_json=meta_str,
        )
        self._s.add(entry)
        await self._s.flush()