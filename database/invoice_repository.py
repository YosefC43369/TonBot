"""
InvoicePayment repository — all SQL for invoice_payments goes here.

No business logic — validation and state-machine enforcement live in
InvoiceService. This layer only translates between Python objects and
the database.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import InvoicePayment, InvoiceStatus


class DuplicateInvoiceRefError(Exception):
    """Raised when a public_ref collision occurs on create()."""


class InvoiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, invoice: InvoicePayment) -> InvoicePayment:
        """
        Persist a new invoice.

        Raises:
            DuplicateInvoiceRefError: public_ref already exists.
        """
        self._s.add(invoice)
        try:
            await self._s.flush()
        except IntegrityError as exc:
            await self._s.rollback()
            raise DuplicateInvoiceRefError(
                f"public_ref {invoice.public_ref!r} already exists"
            ) from exc
        return invoice

    async def get_by_public_ref(self, public_ref: str) -> InvoicePayment | None:
        result = await self._s.execute(
            select(InvoicePayment).where(InvoicePayment.public_ref == public_ref)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InvoicePayment]:
        result = await self._s.execute(
            select(InvoicePayment)
            .where(InvoicePayment.user_id == user_id)
            .order_by(InvoicePayment.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_pending(self) -> list[InvoicePayment]:
        """Return all PENDING invoices (not yet expired, not yet detected)."""
        result = await self._s.execute(
            select(InvoicePayment)
            .where(InvoicePayment.status == InvoiceStatus.PENDING)
            .order_by(InvoicePayment.created_at)
        )
        return list(result.scalars().all())

    async def list_pending_not_expired(self, now: datetime) -> list[InvoicePayment]:
        """Return PENDING invoices whose expiry is still in the future."""
        result = await self._s.execute(
            select(InvoicePayment)
            .where(
                InvoicePayment.status == InvoiceStatus.PENDING,
                InvoicePayment.expires_at > now,
            )
            .order_by(InvoicePayment.created_at)
        )
        return list(result.scalars().all())

    async def expire_pending(self, now: datetime) -> int:
        """
        Bulk-expire all PENDING invoices whose expires_at <= now.
        Returns the number of rows updated.
        """
        result = await self._s.execute(
            update(InvoicePayment)
            .where(
                InvoicePayment.status == InvoiceStatus.PENDING,
                InvoicePayment.expires_at <= now,
            )
            .values(status=InvoiceStatus.EXPIRED)
        )
        return result.rowcount  # type: ignore[return-value]

    async def transition(
        self,
        invoice: InvoicePayment,
        next_status: str,
        *,
        provider_tx_ref: str | None = None,
        detected_at: datetime | None = None,
        confirmed_at: datetime | None = None,
    ) -> InvoicePayment:
        """
        Apply a state change to an invoice and flush.

        Only fields explicitly passed are updated; None means "no change."
        """
        invoice.status = next_status
        if provider_tx_ref is not None:
            invoice.provider_tx_ref = provider_tx_ref
        if detected_at is not None:
            invoice.detected_at = detected_at
        if confirmed_at is not None:
            invoice.confirmed_at = confirmed_at
        self._s.add(invoice)
        await self._s.flush()
        return invoice

    async def find_pending_by_ref_comment(
        self,
        comment: str,
    ) -> InvoicePayment | None:
        """
        Return the single PENDING invoice whose public_ref appears in the
        transaction comment string, or None.

        The comment is the memo attached to a TON transfer.  The payer is
        instructed to include the invoice public_ref verbatim as the memo.
        """
        result = await self._s.execute(
            select(InvoicePayment).where(
                InvoicePayment.status == InvoiceStatus.PENDING,
                InvoicePayment.public_ref == comment.strip(),
            )
        )
        return result.scalar_one_or_none()

    async def find_by_provider_tx_ref(
        self, provider_tx_ref: str
    ) -> InvoicePayment | None:
        """Look up an invoice by its settled transaction event ID (idempotency)."""
        result = await self._s.execute(
            select(InvoicePayment).where(
                InvoicePayment.provider_tx_ref == provider_tx_ref
            )
        )
        return result.scalar_one_or_none()