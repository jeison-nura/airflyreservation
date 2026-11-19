"""add_booking_api_credentials_and_idempotency

Revision ID: 01a1f4140bea7b5c9e198b351113e1b6
Revises: 01a1f1ec7d8e70d9ba984f17cf641fe3
Create Date: 2026-11-19 08:51:56.910701

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '01a1f4140bea7b5c9e198b351113e1b6'
down_revision: str | Sequence[str] | None = '01a1f1ec7d8e70d9ba984f17cf641fe3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reservations",
        sa.Column("access_credential_hash", sa.String(64), nullable=True),
        schema="reservations",
    )
    op.create_table(
        "passenger_details",
        sa.Column("reservation_id", sa.String(64), nullable=False),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["reservations.reservations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("reservation_id"),
        schema="reservations",
    )
    op.create_table(
        "request_idempotency",
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("reservation_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["reservations.reservations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("operation", "key"),
        schema="reservations",
    )


def downgrade() -> None:
    op.drop_table("request_idempotency", schema="reservations")
    op.drop_table("passenger_details", schema="reservations")
    op.drop_column("reservations", "access_credential_hash", schema="reservations")
