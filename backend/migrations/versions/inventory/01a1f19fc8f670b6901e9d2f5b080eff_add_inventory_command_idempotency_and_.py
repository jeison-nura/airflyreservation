"""Add Inventory command idempotency and transactional outbox.

Revision ID: 01a1f19fc8f670b6901e9d2f5b080eff
Revises: 01a1f1807fbb7f1b93c235d8438ae314
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "01a1f19fc8f670b6901e9d2f5b080eff"
down_revision = "01a1f1807fbb7f1b93c235d8438ae314"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "command_idempotency",
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("outcome", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("operation", "key"),
        schema="inventory",
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("flight_id", sa.String(64), nullable=False),
        sa.Column("seat_number", sa.String(8), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("causation_id", sa.String(64), nullable=False),
        sa.Column("claimed_by", sa.String(64), nullable=True),
        sa.Column("claim_token", sa.String(32), nullable=True),
        sa.Column("claim_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="inventory",
    )
    op.create_index(
        "ix_inventory_outbox_pending",
        "outbox_events",
        ["delivered_at", "claim_until", "occurred_at"],
        schema="inventory",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inventory_outbox_pending", table_name="outbox_events", schema="inventory"
    )
    op.drop_table("outbox_events", schema="inventory")
    op.drop_table("command_idempotency", schema="inventory")
