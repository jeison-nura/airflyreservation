"""add_reservation_messaging_and_saga_operations

Revision ID: 01a1f41e2df37c49a8b85e82b5de814a
Revises: 01a1f4140bea7b5c9e198b351113e1b6
Create Date: 2026-11-19 09:03:00.980332

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '01a1f41e2df37c49a8b85e82b5de814a'
down_revision: str | Sequence[str] | None = '01a1f4140bea7b5c9e198b351113e1b6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saga_operations",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("reservation_id", sa.String(64), nullable=False),
        sa.Column("destination", sa.String(32), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("outcome", sa.JSON(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["reservations.reservations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "destination",
            "operation",
            "idempotency_key",
            name="uq_reservation_saga_operation_key",
        ),
        schema="reservations",
    )
    op.create_table(
        "outbox_events",
        sa.Column("event_id", sa.String(32), nullable=False),
        sa.Column("reservation_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("causation_id", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by", sa.String(64), nullable=True),
        sa.Column("claim_token", sa.String(32), nullable=True),
        sa.Column("claim_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["reservations.reservations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id"),
        schema="reservations",
    )
    op.create_index(
        "ix_reservations_outbox_pending",
        "outbox_events",
        ["delivered_at", "claim_until", "occurred_at"],
        schema="reservations",
    )
    op.create_table(
        "inbox_events",
        sa.Column("consumer", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("consumer", "event_id"),
        schema="reservations",
    )
    op.create_table(
        "dead_letters",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("consumer", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("consumer", "event_id", name="uq_reservation_dead_letter"),
        schema="reservations",
    )
    op.create_table(
        "reservation_notifications",
        sa.Column("notification_id", sa.String(32), nullable=False),
        sa.Column("reservation_id", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["reservations.reservations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("notification_id"),
        sa.UniqueConstraint(
            "reservation_id", "sequence", name="uq_reservation_notification_sequence"
        ),
        schema="reservations",
    )


def downgrade() -> None:
    op.drop_table("reservation_notifications", schema="reservations")
    op.drop_table("dead_letters", schema="reservations")
    op.drop_table("inbox_events", schema="reservations")
    op.drop_index(
        "ix_reservations_outbox_pending",
        table_name="outbox_events",
        schema="reservations",
    )
    op.drop_table("outbox_events", schema="reservations")
    op.drop_table("saga_operations", schema="reservations")
