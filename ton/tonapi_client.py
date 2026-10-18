"""
TonAPI v2 read-only adapter.

Endpoints used:
  GET /v2/accounts/{account_id}                       — account info + TON balance
  GET /v2/accounts/{account_id}/jettons?currencies=ton,usd — Jetton balances
  GET /v2/accounts/{account_id}/events?limit=N        — transaction events

Pagination:
  /events uses `before_lt` cursor from the `next_from` field in the response.

Authentication:
  Bearer token via Authorization header (set in BaseHTTPClient).

Rate limits:
  TonAPI free tier: ~10 req/s. Paid tiers higher. Retry-After respected.

Limitations:
  - Transaction `in_progress: true` events are NOT treated as confirmed.
  - A zero balance is explicitly distinguished from an account-not-found 404.
  - NFT retrieval is not included in Phase 1 (clean foundation first).
"""

from __future__ import annotations

from typing import Any

from ton.base_client import AccountNotFoundError, BaseHTTPClient, ProviderError
from ton.schemas import AccountInfo, JettonsResponse, Transaction, TransactionsResponse

_DEFAULT_EVENT_LIMIT = 20
_MAX_EVENT_LIMIT = 100


class TonApiClient(BaseHTTPClient):
    """Read-only TonAPI v2 client. Use as an async context manager."""
    
    async def get_account(self, address: str) -> AccountInfo:
        """
        Retrieve account information including TON balance in nanotons.

        Args:
            address: canonical TON address string.

        Returns:
            AccountInfo. balance == 0 and status == "nonexist" for new accounts.

        Raises:
            AccountNotFoundError: provider returned 404.
            ProviderError: on unrecoverable provider failure.
        """
        data: dict[str, Any] = await self.get(f"/v2/accounts/{address}")
        return AccountInfo.model_validate(data)

    async def get_jetton_balances(self, address: str) -> JettonsResponse:
        """
        Retrieve Jetton (fungible token) balances for an account.

        Args:
            address: canonical TON address.

        Returns:
            JettonsResponse with a list of JettonBalance entries.
            Returns empty balances list if the account holds no Jettons.
        """
        try:
            data: dict[str, Any] = await self.get(
                f"/v2/accounts/{address}/jettons",
                params={"currencies": "ton,usd"},
            )
            return JettonsResponse.model_validate(data)
        except AccountNotFoundError:
            # Account with no history returns 404 for Jetton endpoint
            return JettonsResponse(balances=[])

    async def get_events(
        self,
        address: str,
        limit: int = _DEFAULT_EVENT_LIMIT,
        before_lt: int | None = None,
    ) -> TransactionsResponse:
        """
        Retrieve transaction events for an account (newest first).

        Args:
            address:   canonical TON address.
            limit:     max events per page (1–100).
            before_lt: logical time cursor for pagination (from `next_from`).

        Returns:
            TransactionsResponse. next_from is None when no more pages exist.
            Returns empty events list for accounts with no transactions.
        """
        limit = max(1, min(limit, _MAX_EVENT_LIMIT))
        params: dict[str, Any] = {"limit": limit, "subject_only": "true"}
        if before_lt is not None:
            params["before_lt"] = before_lt

        try:
            data: dict[str, Any] = await self.get(
                f"/v2/accounts/{address}/events",
                params=params,
            )
            return TransactionsResponse.model_validate(data)
        except AccountNotFoundError:
            return TransactionsResponse(events=[], next_from=None)

    async def get_all_events(
        self,
        address: str,
        max_pages: int = 10,
    ) -> list[Transaction]:
        """
        Fetch up to `max_pages` pages of events.

        Stops when next_from is None or max_pages is reached.
        Intended for initial backfill only; ongoing monitoring uses get_events.
        """
        events: list[Transaction] = []
        cursor: int | None = None

        for _ in range(max_pages):
            page = await self.get_events(
                address,
                limit=_MAX_EVENT_LIMIT,
                before_lt=cursor,
            )
            events.extend(page.events)
            if page.next_from is None:
                break
            cursor = page.next_from

        return events