"""Add receiving_address to invoice_payments; add late status

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add receiving_address column (NOT NULL — fill with placeholder for existing rows)
    op.add_column(
        "invoice_payments",
        sa.Column(
            "receiving_address",
            sa.String(128),
            nullable=False,
            server_default="UNKNOWN",
        ),
    )
    # Remove the server default after backfill — application must always supply it
    op.alter_column("invoice_payments", "receiving_address", server_default=None)

    # Index for monitor queries: find pending invoices by receiving address
    op.create_index(
        "ix_invoice_receiving_address",
        "invoice_payments",
        ["receiving_address"],
    )
    # 'late' is purely a status string value in the CHECK constraint, no schema change needed.
    # The column already accepts any varchar(32).


def downgrade() -> None:
    op.drop_index("ix_invoice_receiving_address", table_name="invoice_payments")
    op.drop_column("invoice_payments", "receiving_address")