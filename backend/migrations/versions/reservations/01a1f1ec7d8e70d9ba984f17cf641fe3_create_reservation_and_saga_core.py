"""Create Reservations core aggregate in its own schema.

Revision ID: 01a1f1ec7d8e70d9ba984f17cf641fe3
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "01a1f1ec7d8e70d9ba984f17cf641fe3"
down_revision = None
branch_labels = ("reservations",)
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS reservations")
    op.create_table(
        "reservations",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("flight_id", sa.String(64), nullable=False),
        sa.Column("seat_number", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("booking_code", sa.String(32), nullable=True),
        sa.Column("failure_reason", sa.String(64), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'FAILED', 'EXPIRED')",
            name="ck_reservations_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_reservations_version"),
        sa.CheckConstraint("expires_at > created_at", name="ck_reservations_expiry"),
        sa.CheckConstraint(
            "(status = 'CONFIRMED' AND booking_code IS NOT NULL AND failure_reason IS NULL)"
            " OR (status = 'FAILED' AND failure_reason IS NOT NULL AND booking_code IS NULL)"
            " OR (status IN ('PENDING', 'EXPIRED') AND booking_code IS NULL"
            " AND failure_reason IS NULL)",
            name="ck_reservations_outcome",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("booking_code"),
        schema="reservations",
    )
    op.create_table(
        "reservation_sagas",
        sa.Column("reservation_id", sa.String(64), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("step", sa.String(32), nullable=False),
        sa.Column("compensation_status", sa.String(16), nullable=False),
        sa.Column("payment_attempt_ref", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["reservations.reservations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("reservation_id"),
        schema="reservations",
    )


def downgrade() -> None:
    op.drop_table("reservation_sagas", schema="reservations")
    op.drop_table("reservations", schema="reservations")
    op.execute("DROP SCHEMA reservations")
