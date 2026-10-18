"""
Balance retrieval service.

Fetches TON and Jetton balances from the provider.
Converts amounts using exact Decimal arithmetic.
Distinguishes zero balances from account-not-found.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from ton.address import AddressValidationError, parse_address
from ton.base_client import AccountNotFoundError, ProviderError
from ton.schemas import AccountInfo
from ton.tonapi_client import TonApiClient
from ton.units import format_jetton, format_ton, nanoton_to_ton


@dataclass(frozen=True)
class JettonBalanceInfo:
    symbol: str
    name: str
    address: str
    decimals: int
    formatted_balance: str
    raw_balance: int
    verification: str
    
    
@dataclass(frozen=True)
class AccountBalanceResult:
    canonical_address: str
    status: str                     # "active" | "nonexist" | "frozen" | etc.
    ton_nanotons: int
    ton_formatted: str              # e.g. "12.5"
    account_name: str | None
    is_scam: bool
    jettons: list[JettonBalanceInfo] = field(default_factory=list)
    as_of: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    account_not_found: bool = False
    
    
class BalanceService:
    def __init__(self, ton_client: TonApiClient) -> None:
        self._client = ton_client

    async def get_balance(self, raw_address: str) -> AccountBalanceResult:
        """
        Retrieve TON balance for an address.

        Returns an AccountBalanceResult with account_not_found=True if the
        address has never been initialized on-chain (distinct from 0 balance).

        Raises:
            AddressValidationError: invalid address string.
            ProviderError: unrecoverable provider failure.
        """
        addr = parse_address(raw_address)

        try:
            info: AccountInfo = await self._client.get_account(addr.canonical)
        except AccountNotFoundError:
            return AccountBalanceResult(
                canonical_address=addr.canonical,
                status="nonexist",
                ton_nanotons=0,
                ton_formatted="0",
                account_name=None,
                is_scam=False,
                account_not_found=True,
            )

        jetton_infos: list[JettonBalanceInfo] = []
        try:
            jettons = await self._client.get_jetton_balances(addr.canonical)
            for jb in jettons.balances:
                if jb.jetton.verification == "blacklist":
                    continue
                try:
                    formatted = format_jetton(jb.raw_balance, jb.jetton.decimals)
                except (ValueError, ArithmeticError):
                    formatted = str(jb.raw_balance)
                jetton_infos.append(
                    JettonBalanceInfo(
                        symbol=jb.jetton.symbol,
                        name=jb.jetton.name,
                        address=jb.jetton.address,
                        decimals=jb.jetton.decimals,
                        formatted_balance=formatted,
                        raw_balance=jb.raw_balance,
                        verification=jb.jetton.verification,
                    )
                )
        except ProviderError:
            # Jetton retrieval is best-effort — don't fail the whole balance call
            pass

        return AccountBalanceResult(
            canonical_address=addr.canonical,
            status=info.status,
            ton_nanotons=info.balance,
            ton_formatted=format_ton(info.balance),
            account_name=info.name,
            is_scam=info.is_scam,
            jettons=sorted(jetton_infos, key=lambda j: j.symbol),
        )