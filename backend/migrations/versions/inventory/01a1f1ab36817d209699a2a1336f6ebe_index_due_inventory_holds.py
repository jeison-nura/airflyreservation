"""Index due Inventory holds for bounded worker polling.

Revision ID: 01a1f1ab36817d209699a2a1336f6ebe
Revises: 01a1f19fc8f670b6901e9d2f5b080eff
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "01a1f1ab36817d209699a2a1336f6ebe"
down_revision = "01a1f19fc8f670b6901e9d2f5b080eff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_inventory_seats_due",
        "flight_seats",
        ["status", "hold_expires_at", "flight_id", "seat_number"],
        schema="inventory",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inventory_seats_due", table_name="flight_seats", schema="inventory"
    )
