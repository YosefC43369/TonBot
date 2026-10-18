"""
Wallet watchlist service.

All authorization and business rules live here, not in handlers.
A user can only read and modify their own watchlist.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import WatchlistEntry
from database.repositories import AuditRepository, UserRepository, WatchlistRepository
from ton.address import AddressValidationError, NormalizedAddress, parse_address


class WatchlistError(Exception):
    """Base for watchlist business-logic errors."""


class WatchlistFull(WatchlistError):
    """User has reached the per-user watchlist limit."""


class WatchlistDuplicate(WatchlistError):
    """Address is already on the user's watchlist."""


class WatchlistNotFound(WatchlistError):
    """Address is not on the user's watchlist."""


@dataclass
class WatchlistResult:
    entry: WatchlistEntry
    address: NormalizedAddress


class WalletService:
    def __init__(
        self,
        session: AsyncSession,
        max_per_user: int = 20,
    ) -> None:
        self._session = session
        self._max_per_user = max_per_user
        self._users = UserRepository(session)
        self._watchlist = WatchlistRepository(session)
        self._audit = AuditRepository(session)

    async def _require_user(self, telegram_id: int) -> int:
        """Get or create a User row; return its internal DB id."""
        user, _ = await self._users.get_or_create(telegram_id)
        return user.id

    async def add_wallet(
        self,
        telegram_id: int,
        raw_address: str,
        label: str | None = None,
    ) -> WatchlistResult:
        """
        Add a wallet address to a user's watchlist.

        Raises:
            AddressValidationError: if the address is invalid.
            WatchlistFull: if the user has reached the limit.
            WatchlistDuplicate: if the address is already watched.
        """
        addr = parse_address(raw_address)  # may raise AddressValidationError
        user_id = await self._require_user(telegram_id)

        count = await self._watchlist.count_for_user(user_id)
        if count >= self._max_per_user:
            raise WatchlistFull(
                f"Watchlist limit reached ({self._max_per_user}). "
                "Remove an address before adding a new one."
            )

        entry = await self._watchlist.add(
            user_id=user_id,
            canonical_address=addr.canonical,
            label=label,
        )
        if entry is None:
            raise WatchlistDuplicate(
                f"Address {addr.canonical!r} is already on your watchlist."
            )

        await self._audit.record(
            action="watchlist_add",
            actor_telegram_id=telegram_id,
            resource_ref=addr.canonical,
        )

        return WatchlistResult(entry=entry, address=addr)

    async def remove_wallet(
        self,
        telegram_id: int,
        raw_address: str,
    ) -> NormalizedAddress:
        """
        Remove a wallet address from a user's watchlist.

        Raises:
            AddressValidationError: if the address is invalid.
            WatchlistNotFound: if the address is not on the watchlist.
        """
        addr = parse_address(raw_address)
        user_id = await self._require_user(telegram_id)

        removed = await self._watchlist.remove(
            user_id=user_id,
            canonical_address=addr.canonical,
        )
        if not removed:
            raise WatchlistNotFound(
                f"Address {addr.canonical!r} is not on your watchlist."
            )

        await self._audit.record(
            action="watchlist_remove",
            actor_telegram_id=telegram_id,
            resource_ref=addr.canonical,
        )

        return addr

    async def list_wallets(self, telegram_id: int) -> list[WatchlistEntry]:
        """
        Return all active watchlist entries for a user.
        Only the user's own entries are returned.
        """
        user_id = await self._require_user(telegram_id)
        return await self._watchlist.list_for_user(user_id)

    async def get_wallet(
        self,
        telegram_id: int,
        raw_address: str,
    ) -> WatchlistEntry:
        """
        Return a single watchlist entry owned by this user.

        Raises:
            AddressValidationError: if the address is invalid.
            WatchlistNotFound: if the entry doesn't exist.
        """
        addr = parse_address(raw_address)
        user_id = await self._require_user(telegram_id)

        entry = await self._watchlist.get(
            user_id=user_id,
            canonical_address=addr.canonical,
        )
        if entry is None:
            raise WatchlistNotFound(
                f"Address {addr.canonical!r} is not on your watchlist."
            )
        return entry