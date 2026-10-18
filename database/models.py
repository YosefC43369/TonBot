"""
SQLAlchemy 2.x ORM models.

Tables:
  users            — Telegram users by numeric ID
  watchlists       — per-user wallet watchlist entries
  transactions     — deduplication log for on-chain events
  provider_cursors — per-address pagination checkpoints
  audit_logs       — actor/action audit trail

No private keys or seed phrases are ever stored.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    """Registered Telegram users identified by numeric Telegram ID."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    watchlist_entries: Mapped[list["WatchlistEntry"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User telegram_id={self.telegram_id}>"


class WatchlistEntry(Base):
    """
    A single wallet address watched by a user.

    `canonical_address` stores the bounceable base64url form so that
    different textual representations of the same account collapse to one row.
    """

    __tablename__ = "watchlists"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "canonical_address", name="uq_watchlist_user_address"
        ),
        Index("ix_watchlists_user_id", "user_id"),
        Index("ix_watchlists_canonical_address", "canonical_address"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    canonical_address: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped["User"] = relationship(back_populates="watchlist_entries")

    def __repr__(self) -> str:
        return f"<WatchlistEntry user_id={self.user_id} addr={self.canonical_address!r}>"


class TransactionRecord(Base):
    """
    Deduplication log for on-chain events fetched from the provider.

    `provider_event_id` is the event_id from TonAPI — unique per event.
    `raw_action_type` and `status` are normalized strings, not provider verbatim.
    `source_metadata` stores enough raw data for reconciliation without
     persisting the entire response indefinitely.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint(
            "provider_event_id", name="uq_transactions_provider_event_id"
        ),
        Index("ix_transactions_canonical_address", "canonical_address"),
        Index("ix_transactions_timestamp", "tx_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_address: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(256), nullable=False)
    tx_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    raw_action_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown"
    )
    # Compact JSON metadata — not the entire provider response
    source_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<TransactionRecord event_id={self.provider_event_id!r}>"


class ProviderCursor(Base):
    """
    Pagination checkpoint per (provider, address) pair.

    `cursor_value` stores the `next_from` logical time returned by TonAPI.
    Reset to NULL when a full rescan is needed.
    """

    __tablename__ = "provider_cursors"
    __table_args__ = (
        UniqueConstraint(
            "provider_id", "canonical_address", name="uq_cursor_provider_address"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False, default="tonapi")
    canonical_address: Mapped[str] = mapped_column(String(128), nullable=False)
    cursor_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<ProviderCursor provider={self.provider_id!r} "
            f"addr={self.canonical_address!r} cursor={self.cursor_value!r}>"
        )


class AuditLog(Base):
    """Immutable append-only audit trail. Never updated, only inserted."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_actor_id", "actor_telegram_id"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    # Sanitized — no secrets, no raw provider data with credentials
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<AuditLog action={self.action!r} actor={self.actor_telegram_id}>"