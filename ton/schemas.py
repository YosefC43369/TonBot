"""
Typed schemas for TonAPI v2 responses.

References: https://tonapi.io/api-v2
All fields are optional-safe — provider may omit fields for uninitialized accounts.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class AccountInfo(BaseModel):
    """GET /v2/accounts/{account_id}"""

    address: str
    balance: int = Field(default=0, description="Balance in nanotons")
    status: str = Field(default="nonexist")
    name: str | None = None
    is_scam: bool = False
    last_activity: int | None = None  # unix timestamp

    @field_validator("balance", mode="before")
    @classmethod
    def coerce_balance(cls, v: Any) -> int:
        """Provider returns balance as a JSON number or string."""
        return int(v)


class JettonPreview(BaseModel):
    address: str
    name: str
    symbol: str
    decimals: int
    image: str | None = None
    verification: str = "none"


class JettonBalance(BaseModel):
    balance: str  # raw integer string
    wallet_address: dict[str, Any]
    jetton: JettonPreview
    price: dict[str, Any] | None = None

    @property
    def raw_balance(self) -> int:
        return int(self.balance)


class JettonsResponse(BaseModel):
    """GET /v2/accounts/{account_id}/jettons"""

    balances: list[JettonBalance] = Field(default_factory=list)


class TransactionMessage(BaseModel):
    hash: str | None = None
    lt: int | None = None
    source: dict[str, Any] | None = None
    destination: dict[str, Any] | None = None
    value: int | None = None
    value_flow: dict[str, Any] | None = None
    op_code: str | None = None
    decoded_op_name: str | None = None
    decoded_body: dict[str, Any] | None = None


class Transaction(BaseModel):
    """Single entry in GET /v2/accounts/{account_id}/events"""

    event_id: str
    timestamp: int
    fees: dict[str, Any] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    lt: int | None = None
    in_progress: bool = False
    is_scam: bool = False


class TransactionsResponse(BaseModel):
    """GET /v2/accounts/{account_id}/events"""

    events: list[Transaction] = Field(default_factory=list)
    next_from: int | None = None  # cursor for pagination