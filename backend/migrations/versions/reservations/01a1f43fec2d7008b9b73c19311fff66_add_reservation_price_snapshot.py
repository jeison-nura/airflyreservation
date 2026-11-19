"""add_reservation_price_snapshot

Revision ID: 01a1f43fec2d7008b9b73c19311fff66
Revises: 01a1f41e2df37c49a8b85e82b5de814a
Create Date: 2026-11-19 09:39:52.366578

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '01a1f43fec2d7008b9b73c19311fff66'
down_revision: str | Sequence[str] | None = '01a1f41e2df37c49a8b85e82b5de814a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reservations",
        sa.Column("amount", sa.Numeric(precision=14, scale=4), nullable=True),
        schema="reservations",
    )
    op.add_column(
        "reservations",
        sa.Column("currency", sa.String(3), nullable=True),
        schema="reservations",
    )
    op.create_check_constraint(
        "ck_reservations_price_snapshot",
        "reservations",
        "(amount IS NULL AND currency IS NULL) OR "
        "(amount > 0 AND currency IS NOT NULL)",
        schema="reservations",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_reservations_price_snapshot", "reservations", schema="reservations"
    )
    op.drop_column("reservations", "currency", schema="reservations")
    op.drop_column("reservations", "amount", schema="reservations")
