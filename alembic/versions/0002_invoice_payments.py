"""Invoice payments table — Phase 2A

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoice_payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_ref", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("asset_type", sa.String(32), nullable=False, server_default="TON"),
        sa.Column("amount_nanotons", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("provider_tx_ref", sa.String(256), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_ref", name="uq_invoice_public_ref"),
    )
    op.create_index("ix_invoice_user_id", "invoice_payments", ["user_id"])
    op.create_index("ix_invoice_status", "invoice_payments", ["status"])
    op.create_index("ix_invoice_expires_at", "invoice_payments", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_invoice_expires_at", table_name="invoice_payments")
    op.drop_index("ix_invoice_status", table_name="invoice_payments")
    op.drop_index("ix_invoice_user_id", table_name="invoice_payments")
    op.drop_table("invoice_payments")