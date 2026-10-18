"""
Unit tests for Phase 2A invoice persistence and service layer.

Uses an in-memory SQLite database via SQLAlchemy async so no Postgres
or network connection is required. All external services are absent —
the InvoiceService and InvoiceRepository only touch the DB layer.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.models import Base, InvoiceStatus, User
from database.invoice_repository import DuplicateInvoiceRefError, InvoiceRepository
from database.invoice_service import (
    InvoiceAmountInvalid,
    InvoiceAuthorizationError,
    InvoiceExpiryInvalid,
    InvoiceNotFound,
    InvoiceService,
    InvoiceTransitionError,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture()
async def session(engine) -> AsyncSession:
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as sess:
        yield sess
        await sess.rollback()


@pytest_asyncio.fixture()
async def service(session: AsyncSession) -> InvoiceService:
    return InvoiceService(session)


# Telegram IDs for test users
_USER_A = 1001
_USER_B = 1002


# ── State machine ─────────────────────────────────────────────────────────────


class TestInvoiceStatusTransitions:
    def test_pending_to_expired_allowed(self):
        assert InvoiceStatus.can_transition(InvoiceStatus.PENDING, InvoiceStatus.EXPIRED)

    def test_pending_to_detected_allowed(self):
        assert InvoiceStatus.can_transition(InvoiceStatus.PENDING, InvoiceStatus.DETECTED)

    def test_detected_to_confirmed_allowed(self):
        assert InvoiceStatus.can_transition(InvoiceStatus.DETECTED, InvoiceStatus.CONFIRMED)

    def test_detected_to_underpaid_allowed(self):
        assert InvoiceStatus.can_transition(InvoiceStatus.DETECTED, InvoiceStatus.UNDERPAID)

    def test_detected_to_overpaid_allowed(self):
        assert InvoiceStatus.can_transition(InvoiceStatus.DETECTED, InvoiceStatus.OVERPAID)

    def test_pending_to_confirmed_not_allowed(self):
        # Cannot skip detected — no blockchain evidence in this path
        assert not InvoiceStatus.can_transition(InvoiceStatus.PENDING, InvoiceStatus.CONFIRMED)

    def test_confirmed_is_terminal(self):
        for s in (
            InvoiceStatus.PENDING,
            InvoiceStatus.DETECTED,
            InvoiceStatus.EXPIRED,
            InvoiceStatus.UNDERPAID,
            InvoiceStatus.OVERPAID,
        ):
            assert not InvoiceStatus.can_transition(InvoiceStatus.CONFIRMED, s)

    def test_expired_is_terminal(self):
        for s in (InvoiceStatus.PENDING, InvoiceStatus.DETECTED, InvoiceStatus.CONFIRMED):
            assert not InvoiceStatus.can_transition(InvoiceStatus.EXPIRED, s)

    def test_underpaid_is_terminal(self):
        assert not InvoiceStatus.can_transition(InvoiceStatus.UNDERPAID, InvoiceStatus.CONFIRMED)

    def test_overpaid_is_terminal(self):
        assert not InvoiceStatus.can_transition(InvoiceStatus.OVERPAID, InvoiceStatus.CONFIRMED)


# ── Amount validation ─────────────────────────────────────────────────────────


class TestAmountValidation:
    @pytest.mark.asyncio
    async def test_zero_amount_raises(self, service: InvoiceService):
        with pytest.raises(InvoiceAmountInvalid):
            await service.create_invoice(_USER_A, 0)

    @pytest.mark.asyncio
    async def test_negative_amount_raises(self, service: InvoiceService):
        with pytest.raises(InvoiceAmountInvalid):
            await service.create_invoice(_USER_A, -1)

    @pytest.mark.asyncio
    async def test_float_amount_raises(self, service: InvoiceService):
        with pytest.raises(InvoiceAmountInvalid):
            await service.create_invoice(_USER_A, 0.5)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_above_ceiling_raises(self, service: InvoiceService):
        with pytest.raises(InvoiceAmountInvalid):
            await service.create_invoice(_USER_A, 10_000_001 * 1_000_000_000)

    @pytest.mark.asyncio
    async def test_minimum_valid_amount(self, service: InvoiceService):
        result = await service.create_invoice(_USER_A, 1)
        assert result.amount_nanotons == 1

    @pytest.mark.asyncio
    async def test_large_valid_amount(self, service: InvoiceService):
        result = await service.create_invoice(_USER_A, 1_000_000_000_000)
        assert result.amount_nanotons == 1_000_000_000_000


# ── Expiry validation ─────────────────────────────────────────────────────────


class TestExpiryValidation:
    @pytest.mark.asyncio
    async def test_ttl_too_short_raises(self, service: InvoiceService):
        with pytest.raises(InvoiceExpiryInvalid):
            await service.create_invoice(_USER_A, 1_000_000_000, ttl_seconds=59)

    @pytest.mark.asyncio
    async def test_ttl_too_long_raises(self, service: InvoiceService):
        with pytest.raises(InvoiceExpiryInvalid):
            await service.create_invoice(_USER_A, 1_000_000_000, ttl_seconds=7 * 24 * 3600 + 1)

    @pytest.mark.asyncio
    async def test_float_ttl_raises(self, service: InvoiceService):
        with pytest.raises(InvoiceExpiryInvalid):
            await service.create_invoice(_USER_A, 1_000_000_000, ttl_seconds=3600.5)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_minimum_ttl_valid(self, service: InvoiceService):
        result = await service.create_invoice(_USER_A, 1_000_000_000, ttl_seconds=60)
        assert result.status == InvoiceStatus.PENDING

    @pytest.mark.asyncio
    async def test_expires_at_is_in_future(self, service: InvoiceService):
        now = datetime.now(timezone.utc)
        result = await service.create_invoice(_USER_A, 1_000_000_000, ttl_seconds=3600)
        assert result.expires_at > now


# ── Create and retrieve ───────────────────────────────────────────────────────


class TestCreateAndRetrieve:
    @pytest.mark.asyncio
    async def test_create_returns_pending(self, service: InvoiceService):
        result = await service.create_invoice(_USER_A, 1_000_000_000)
        assert result.status == InvoiceStatus.PENDING
        assert result.public_ref  # non-empty UUID string
        assert result.amount_nanotons == 1_000_000_000
        assert result.asset_type == "TON"
        assert result.provider_tx_ref is None
        assert result.detected_at is None
        assert result.confirmed_at is None

    @pytest.mark.asyncio
    async def test_retrieve_by_public_ref(self, service: InvoiceService):
        created = await service.create_invoice(_USER_A, 2_000_000_000)
        fetched = await service.get_invoice(_USER_A, created.public_ref)
        assert fetched.public_ref == created.public_ref
        assert fetched.amount_nanotons == 2_000_000_000

    @pytest.mark.asyncio
    async def test_public_refs_are_unique(self, service: InvoiceService):
        a = await service.create_invoice(_USER_A, 1_000_000_000)
        b = await service.create_invoice(_USER_A, 1_000_000_000)
        assert a.public_ref != b.public_ref

    @pytest.mark.asyncio
    async def test_not_found_raises(self, service: InvoiceService):
        with pytest.raises(InvoiceNotFound):
            await service.get_invoice(_USER_A, "00000000-0000-0000-0000-000000000000")


# ── Authorization ─────────────────────────────────────────────────────────────


class TestAuthorization:
    @pytest.mark.asyncio
    async def test_user_cannot_read_other_user_invoice(self, service: InvoiceService):
        created = await service.create_invoice(_USER_A, 1_000_000_000)
        with pytest.raises(InvoiceAuthorizationError):
            await service.get_invoice(_USER_B, created.public_ref)

    @pytest.mark.asyncio
    async def test_list_returns_only_own_invoices(self, service: InvoiceService):
        await service.create_invoice(_USER_A, 1_000_000_000)
        await service.create_invoice(_USER_A, 2_000_000_000)
        await service.create_invoice(_USER_B, 3_000_000_000)

        a_list = await service.list_invoices(_USER_A)
        b_list = await service.list_invoices(_USER_B)

        assert len(a_list) == 2
        assert len(b_list) == 1
        assert all(inv.amount_nanotons in (1_000_000_000, 2_000_000_000) for inv in a_list)
        assert b_list[0].amount_nanotons == 3_000_000_000

    @pytest.mark.asyncio
    async def test_empty_list_for_new_user(self, service: InvoiceService):
        result = await service.list_invoices(9999)
        assert result == []


# ── Expiration ────────────────────────────────────────────────────────────────


class TestExpiration:
    @pytest.mark.asyncio
    async def test_expired_invoices_are_updated(self, service: InvoiceService, session: AsyncSession):
        # Create an invoice with a 60s TTL, then artificially wind back expires_at
        inv = await service.create_invoice(_USER_A, 1_000_000_000, ttl_seconds=60)

        # Push expires_at into the past directly via the repository
        from database.models import InvoicePayment
        from sqlalchemy import update

        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.execute(
            update(InvoicePayment)
            .where(InvoicePayment.public_ref == inv.public_ref)
            .values(expires_at=past)
        )
        await session.flush()

        count = await service.expire_pending_invoices()
        assert count == 1

        updated = await service.get_invoice(_USER_A, inv.public_ref)
        assert updated.status == InvoiceStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_future_invoices_not_expired(self, service: InvoiceService):
        await service.create_invoice(_USER_A, 1_000_000_000, ttl_seconds=3600)
        count = await service.expire_pending_invoices()
        assert count == 0

    @pytest.mark.asyncio
    async def test_expire_returns_count(self, service: InvoiceService, session: AsyncSession):
        from database.models import InvoicePayment
        from sqlalchemy import update

        for _ in range(3):
            inv = await service.create_invoice(_USER_A, 1_000_000_000, ttl_seconds=60)
            past = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.execute(
                update(InvoicePayment)
                .where(InvoicePayment.public_ref == inv.public_ref)
                .values(expires_at=past)
            )
        await session.flush()

        count = await service.expire_pending_invoices()
        assert count == 3


# ── State transitions ─────────────────────────────────────────────────────────


class TestStateTransitions:
    @pytest.mark.asyncio
    async def test_pending_to_detected(self, service: InvoiceService):
        inv = await service.create_invoice(_USER_A, 1_000_000_000)
        updated = await service.transition_invoice(
            _USER_A,
            inv.public_ref,
            InvoiceStatus.DETECTED,
            provider_tx_ref="event-abc-123",
            detected_at=datetime.now(timezone.utc),
        )
        assert updated.status == InvoiceStatus.DETECTED
        assert updated.provider_tx_ref == "event-abc-123"
        assert updated.detected_at is not None

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self, service: InvoiceService):
        inv = await service.create_invoice(_USER_A, 1_000_000_000)
        with pytest.raises(InvoiceTransitionError):
            await service.transition_invoice(
                _USER_A, inv.public_ref, InvoiceStatus.CONFIRMED
            )

    @pytest.mark.asyncio
    async def test_transition_on_wrong_user_raises(self, service: InvoiceService):
        inv = await service.create_invoice(_USER_A, 1_000_000_000)
        with pytest.raises(InvoiceAuthorizationError):
            await service.transition_invoice(
                _USER_B, inv.public_ref, InvoiceStatus.DETECTED
            )

    @pytest.mark.asyncio
    async def test_transition_not_found_raises(self, service: InvoiceService):
        with pytest.raises(InvoiceNotFound):
            await service.transition_invoice(
                _USER_A, "no-such-ref", InvoiceStatus.EXPIRED
            )


# ── Repository: duplicate public_ref ─────────────────────────────────────────


class TestRepositoryConstraints:
    @pytest.mark.asyncio
    async def test_duplicate_public_ref_raises(self, session: AsyncSession, engine):
        """
        InvoiceRepository.create() must raise DuplicateInvoiceRefError on
        public_ref collision rather than leaking an IntegrityError.
        """
        from database.models import InvoicePayment, User
        from database.repositories import UserRepository

        users = UserRepository(session)
        user, _ = await users.get_or_create(5555)
        await session.flush()

        repo = InvoiceRepository(session)
        now = datetime.now(timezone.utc)

        inv1 = InvoicePayment(
            public_ref="fixed-ref-for-collision-test",
            user_id=user.id,
            asset_type="TON",
            amount_nanotons=1_000_000_000,
            created_at=now,
            expires_at=now + timedelta(hours=1),
            status=InvoiceStatus.PENDING,
        )
        await repo.create(inv1)
        await session.commit()

        # Start a fresh session to avoid cached state
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as sess2:
            repo2 = InvoiceRepository(sess2)
            inv2 = InvoicePayment(
                public_ref="fixed-ref-for-collision-test",  # same ref
                user_id=user.id,
                asset_type="TON",
                amount_nanotons=2_000_000_000,
                created_at=now,
                expires_at=now + timedelta(hours=1),
                status=InvoiceStatus.PENDING,
            )
            with pytest.raises(DuplicateInvoiceRefError):
                await repo2.create(inv2)