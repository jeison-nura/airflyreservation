"""create_payment_attempts

Revision ID: 01a1f450baf67918aa371dead355ae81
Revises:
Create Date: 2026-11-19 09:58:13.879559

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '01a1f450baf67918aa371dead355ae81'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ('payments',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS payments")
    op.create_table(
        "payment_attempts",
        sa.Column("payment_attempt_ref", sa.String(64), nullable=False),
        sa.Column("reservation_id", sa.String(64), nullable=False),
        sa.Column("amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("authorize_key", sa.String(128), nullable=False),
        sa.Column("capture_key", sa.String(128), nullable=True),
        sa.Column("void_key", sa.String(128), nullable=True),
        sa.Column("refund_key", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('AUTHORIZED', 'DENIED', 'CAPTURED', 'VOIDED', 'REFUNDED')",
            name="ck_payment_attempts_status",
        ),
        sa.CheckConstraint("amount > 0", name="ck_payment_attempts_amount"),
        sa.PrimaryKeyConstraint("payment_attempt_ref"),
        sa.UniqueConstraint("authorize_key"),
        sa.UniqueConstraint("capture_key"),
        sa.UniqueConstraint("void_key"),
        sa.UniqueConstraint("refund_key"),
        schema="payments",
    )
    op.create_index(
        "ix_payments_payment_attempts_reservation_id",
        "payment_attempts",
        ["reservation_id"],
        schema="payments",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payments_payment_attempts_reservation_id",
        table_name="payment_attempts",
        schema="payments",
    )
    op.drop_table("payment_attempts", schema="payments")
    op.execute("DROP SCHEMA payments")
