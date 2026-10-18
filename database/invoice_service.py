"""
Invoice payment service — Phase 2A.

Responsibilities:
- Creating and retrieving invoices.
- User-level authorization (a user can only see their own invoices).
- Amount and expiry validation.
- Expiring eligible unpaid invoices.
- State transition enforcement.

What this service intentionally does NOT do:
- Sign or broadcast transactions.
- Move TON or Jettons.
- Mark invoices confirmed without verified blockchain evidence.
- Accept float amounts — integer nanotons only.

An invoice is not proof of payment.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from database.invoice_repository import DuplicateInvoiceRefError, InvoiceRepository
from database.models import InvoicePayment, InvoiceStatus
from database.repositories import AuditRepository, UserRepository

# ── Constants ─────────────────────────────────────────────────────────────────

_MIN_NANOTONS: int = 1
_MAX_NANOTONS: int = 10_000_000 * 1_000_000_000  # 10 million TON ceiling
_MIN_TTL_SECONDS: int = 60           # 1 minute
_MAX_TTL_SECONDS: int = 7 * 24 * 3600  # 7 days
_DEFAULT_TTL_SECONDS: int = 3600     # 1 hour


# ── Errors ────────────────────────────────────────────────────────────────────


class InvoiceError(Exception):
    """Base for invoice business-logic errors."""


class InvoiceNotFound(InvoiceError):
    """No invoice with the given public_ref exists (or belongs to this user)."""


class InvoiceAmountInvalid(InvoiceError):
    """Amount is zero, negative, non-integer, or exceeds the safety ceiling."""


class InvoiceExpiryInvalid(InvoiceError):
    """TTL is outside the permitted range."""


class InvoiceTransitionError(InvoiceError):
    """Requested status transition is not permitted from the current state."""


class InvoiceAuthorizationError(InvoiceError):
    """The requesting user does not own this invoice."""


# ── Result dataclasses ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InvoiceResult:
    id: int
    public_ref: str
    user_id: int
    asset_type: str
    amount_nanotons: int
    status: str
    created_at: datetime
    expires_at: datetime
    provider_tx_ref: str | None
    detected_at: datetime | None
    confirmed_at: datetime | None


def _to_result(inv: InvoicePayment) -> InvoiceResult:
    return InvoiceResult(
        id=inv.id,
        public_ref=inv.public_ref,
        user_id=inv.user_id,
        asset_type=inv.asset_type,
        amount_nanotons=inv.amount_nanotons,
        status=inv.status,
        created_at=inv.created_at,
        expires_at=inv.expires_at,
        provider_tx_ref=inv.provider_tx_ref,
        detected_at=inv.detected_at,
        confirmed_at=inv.confirmed_at,
    )


# ── Service ───────────────────────────────────────────────────────────────────


class InvoiceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._invoices = InvoiceRepository(session)
        self._users = UserRepository(session)
        self._audit = AuditRepository(session)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _require_user(self, telegram_id: int) -> int:
        """Return the internal user PK, creating the row if absent."""
        user, _ = await self._users.get_or_create(telegram_id)
        return user.id

    @staticmethod
    def _validate_amount(amount_nanotons: int) -> None:
        """
        Raise InvoiceAmountInvalid for any amount outside the safe range.

        Only integers are accepted — float is never valid here.
        """
        if not isinstance(amount_nanotons, int):
            raise InvoiceAmountInvalid(
                f"amount_nanotons must be an integer, got {type(amount_nanotons).__name__}"
            )
        if amount_nanotons < _MIN_NANOTONS:
            raise InvoiceAmountInvalid(
                f"amount_nanotons must be >= {_MIN_NANOTONS} (got {amount_nanotons})"
            )
        if amount_nanotons > _MAX_NANOTONS:
            raise InvoiceAmountInvalid(
                f"amount_nanotons exceeds ceiling {_MAX_NANOTONS} (got {amount_nanotons})"
            )

    @staticmethod
    def _validate_ttl(ttl_seconds: int) -> None:
        if not isinstance(ttl_seconds, int):
            raise InvoiceExpiryInvalid(
                f"ttl_seconds must be an integer, got {type(ttl_seconds).__name__}"
            )
        if ttl_seconds < _MIN_TTL_SECONDS:
            raise InvoiceExpiryInvalid(
                f"ttl_seconds must be >= {_MIN_TTL_SECONDS} (got {ttl_seconds})"
            )
        if ttl_seconds > _MAX_TTL_SECONDS:
            raise InvoiceExpiryInvalid(
                f"ttl_seconds must be <= {_MAX_TTL_SECONDS} (got {ttl_seconds})"
            )

    # ── Public API ────────────────────────────────────────────────────────────

    async def create_invoice(
        self,
        telegram_id: int,
        amount_nanotons: int,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        asset_type: str = "TON",
    ) -> InvoiceResult:
        """
        Create a new payment invoice for the given user.

        - amount_nanotons must be a positive integer.
        - ttl_seconds controls expiry (1 min – 7 days).
        - asset_type is "TON" for Phase 2A.

        Raises:
            InvoiceAmountInvalid: bad amount.
            InvoiceExpiryInvalid: bad TTL.
        """
        self._validate_amount(amount_nanotons)
        self._validate_ttl(ttl_seconds)

        user_id = await self._require_user(telegram_id)
        now = datetime.now(timezone.utc)

        invoice = InvoicePayment(
            public_ref=str(uuid.uuid4()),
            user_id=user_id,
            asset_type=asset_type,
            amount_nanotons=amount_nanotons,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            status=InvoiceStatus.PENDING,
        )

        # UUID4 collision is astronomically improbable — retry once on the
        # theoretical duplicate rather than silently eating the error.
        try:
            invoice = await self._invoices.create(invoice)
        except DuplicateInvoiceRefError:
            invoice.public_ref = str(uuid.uuid4())
            invoice = await self._invoices.create(invoice)

        await self._audit.record(
            action="invoice_created",
            actor_telegram_id=telegram_id,
            resource_ref=invoice.public_ref,
            metadata={"amount_nanotons": amount_nanotons, "asset_type": asset_type},
        )

        return _to_result(invoice)

    async def get_invoice(
        self,
        telegram_id: int,
        public_ref: str,
    ) -> InvoiceResult:
        """
        Return an invoice by public_ref, enforcing user ownership.

        Raises:
            InvoiceNotFound: ref does not exist.
            InvoiceAuthorizationError: ref exists but belongs to another user.
        """
        invoice = await self._invoices.get_by_public_ref(public_ref)
        if invoice is None:
            raise InvoiceNotFound(f"Invoice {public_ref!r} not found")

        user_id = await self._require_user(telegram_id)
        if invoice.user_id != user_id:
            raise InvoiceAuthorizationError(
                f"Invoice {public_ref!r} does not belong to this user"
            )

        return _to_result(invoice)

    async def list_invoices(
        self,
        telegram_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InvoiceResult]:
        """
        Return all invoices owned by telegram_id, newest first.

        Only the calling user's invoices are ever returned.
        """
        user_id = await self._require_user(telegram_id)
        rows = await self._invoices.list_for_user(user_id, limit=limit, offset=offset)
        return [_to_result(r) for r in rows]

    async def expire_pending_invoices(self) -> int:
        """
        Mark all PENDING invoices whose expiry has passed as EXPIRED.

        Intended to be called periodically by a background worker.
        Returns the count of rows changed.
        """
        now = datetime.now(timezone.utc)
        count = await self._invoices.expire_pending(now)
        if count:
            await self._audit.record(
                action="invoices_expired_bulk",
                metadata={"count": count},
            )
        return count

    async def transition_invoice(
        self,
        telegram_id: int,
        public_ref: str,
        next_status: str,
        *,
        provider_tx_ref: str | None = None,
        detected_at: datetime | None = None,
        confirmed_at: datetime | None = None,
    ) -> InvoiceResult:
        """
        Apply a status transition, enforcing the state machine.

        Phase 2A only permits: pending→expired, pending→detected,
        detected→confirmed/underpaid/overpaid.

        Confirmed, underpaid, overpaid, and expired are terminal.

        Raises:
            InvoiceNotFound, InvoiceAuthorizationError, InvoiceTransitionError.
        """
        invoice = await self._invoices.get_by_public_ref(public_ref)
        if invoice is None:
            raise InvoiceNotFound(f"Invoice {public_ref!r} not found")

        user_id = await self._require_user(telegram_id)
        if invoice.user_id != user_id:
            raise InvoiceAuthorizationError(
                f"Invoice {public_ref!r} does not belong to this user"
            )

        if not InvoiceStatus.can_transition(invoice.status, next_status):
            raise InvoiceTransitionError(
                f"Cannot transition invoice from {invoice.status!r} to {next_status!r}"
            )

        invoice = await self._invoices.transition(
            invoice,
            next_status,
            provider_tx_ref=provider_tx_ref,
            detected_at=detected_at,
            confirmed_at=confirmed_at,
        )

        await self._audit.record(
            action="invoice_status_changed",
            actor_telegram_id=telegram_id,
            resource_ref=public_ref,
            metadata={"from": invoice.status, "to": next_status},
        )

        return _to_result(invoice)