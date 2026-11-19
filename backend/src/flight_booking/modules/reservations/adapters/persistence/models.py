"""Initial Reservations tables; no foreign keys into other module schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ReservationRecord(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'FAILED', 'EXPIRED')",
            name="ck_reservations_status",
        ),
        CheckConstraint("version >= 1", name="ck_reservations_version"),
        CheckConstraint("expires_at > created_at", name="ck_reservations_expiry"),
        CheckConstraint(
            "(amount IS NULL AND currency IS NULL) OR "
            "(amount > 0 AND currency IS NOT NULL)",
            name="ck_reservations_price_snapshot",
        ),
        CheckConstraint(
            "(status = 'CONFIRMED' AND booking_code IS NOT NULL AND failure_reason IS NULL)"
            " OR (status = 'FAILED' AND failure_reason IS NOT NULL AND booking_code IS NULL)"
            " OR (status IN ('PENDING', 'EXPIRED') AND booking_code IS NULL"
            " AND failure_reason IS NULL)",
            name="ck_reservations_outcome",
        ),
        {"schema": "reservations"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    flight_id: Mapped[str] = mapped_column(String(64))
    seat_number: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
    booking_code: Mapped[str | None] = mapped_column(String(32), unique=True)
    failure_reason: Mapped[str | None] = mapped_column(String(64))
    access_credential_hash: Mapped[str | None] = mapped_column(String(64))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    currency: Mapped[str | None] = mapped_column(String(3))


class PassengerDetailsRecord(Base):
    __tablename__ = "passenger_details"
    __table_args__ = ({"schema": "reservations"},)

    reservation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reservations.reservations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254))


class RequestIdempotencyRecord(Base):
    __tablename__ = "request_idempotency"
    __table_args__ = ({"schema": "reservations"},)

    operation: Mapped[str] = mapped_column(String(32), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    reservation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reservations.reservations.id", ondelete="CASCADE"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SagaOperationRecord(Base):
    __tablename__ = "saga_operations"
    __table_args__ = (
        UniqueConstraint(
            "destination",
            "operation",
            "idempotency_key",
            name="uq_reservation_saga_operation_key",
        ),
        {"schema": "reservations"},
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    reservation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reservations.reservations.id", ondelete="CASCADE"),
    )
    destination: Mapped[str] = mapped_column(String(32))
    operation: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReservationOutboxRecord(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "ix_reservations_outbox_pending",
            "delivered_at",
            "claim_until",
            "occurred_at",
        ),
        {"schema": "reservations"},
    )

    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    reservation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reservations.reservations.id", ondelete="CASCADE"),
    )
    event_type: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    correlation_id: Mapped[str] = mapped_column(String(64))
    causation_id: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(String(64))
    claim_token: Mapped[str | None] = mapped_column(String(32))
    claim_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class ReservationInboxRecord(Base):
    __tablename__ = "inbox_events"
    __table_args__ = ({"schema": "reservations"},)

    consumer: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    correlation_id: Mapped[str] = mapped_column(String(64))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReservationDeadLetterRecord(Base):
    __tablename__ = "dead_letters"
    __table_args__ = (
        UniqueConstraint(
            "consumer", "event_id", name="uq_reservation_dead_letter"
        ),
        {"schema": "reservations"},
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    consumer: Mapped[str] = mapped_column(String(64))
    event_id: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    failure_code: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReservationNotificationRecord(Base):
    __tablename__ = "reservation_notifications"
    __table_args__ = (
        UniqueConstraint(
            "reservation_id",
            "sequence",
            name="uq_reservation_notification_sequence",
        ),
        {"schema": "reservations"},
    )

    notification_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    reservation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reservations.reservations.id", ondelete="CASCADE"),
    )
    sequence: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReservationSagaRecord(Base):
    __tablename__ = "reservation_sagas"
    __table_args__ = ({"schema": "reservations"},)

    reservation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("reservations.reservations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    correlation_id: Mapped[str] = mapped_column(String(64))
    step: Mapped[str] = mapped_column(String(32))
    compensation_status: Mapped[str] = mapped_column(String(16))
    payment_attempt_ref: Mapped[str | None] = mapped_column(String(64))
