"""Reservation outcome and recoverable saga progress, independent of adapters."""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class ReservationConflict(Exception):
    """The requested reservation transition is not valid."""


class ReservationStatus(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class SagaStep(StrEnum):
    HOLD_REQUESTED = "HOLD_REQUESTED"
    HOLD_OBTAINED = "HOLD_OBTAINED"
    AUTHORIZING = "AUTHORIZING"
    AUTHORIZED = "AUTHORIZED"
    BOOKING_SEAT = "BOOKING_SEAT"
    SEAT_BOOKED = "SEAT_BOOKED"
    CAPTURING = "CAPTURING"
    RECONCILING = "RECONCILING"
    COMPENSATION_PENDING = "COMPENSATION_PENDING"
    DONE = "DONE"


class CompensationStatus(StrEnum):
    NONE = "NONE"
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"


_NEXT_STEPS: dict[SagaStep, frozenset[SagaStep]] = {
    SagaStep.HOLD_REQUESTED: frozenset(
        {SagaStep.HOLD_OBTAINED, SagaStep.COMPENSATION_PENDING, SagaStep.DONE}
    ),
    SagaStep.HOLD_OBTAINED: frozenset(
        {SagaStep.AUTHORIZING, SagaStep.COMPENSATION_PENDING}
    ),
    SagaStep.AUTHORIZING: frozenset(
        {SagaStep.AUTHORIZED, SagaStep.COMPENSATION_PENDING}
    ),
    SagaStep.AUTHORIZED: frozenset(
        {SagaStep.BOOKING_SEAT, SagaStep.COMPENSATION_PENDING}
    ),
    SagaStep.BOOKING_SEAT: frozenset(
        {SagaStep.SEAT_BOOKED, SagaStep.COMPENSATION_PENDING}
    ),
    SagaStep.SEAT_BOOKED: frozenset(
        {SagaStep.CAPTURING, SagaStep.COMPENSATION_PENDING}
    ),
    SagaStep.CAPTURING: frozenset(
        {SagaStep.RECONCILING, SagaStep.COMPENSATION_PENDING, SagaStep.DONE}
    ),
    SagaStep.RECONCILING: frozenset({SagaStep.COMPENSATION_PENDING, SagaStep.DONE}),
    SagaStep.COMPENSATION_PENDING: frozenset({SagaStep.DONE}),
    SagaStep.DONE: frozenset({SagaStep.COMPENSATION_PENDING}),
}


def _required(value: str, maximum: int, label: str) -> None:
    if not value or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must contain 1 to {maximum} characters")


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Reservation timestamps must include a timezone")


@dataclass(frozen=True)
class Reservation:
    id: str
    flight_id: str
    seat_number: str
    status: ReservationStatus
    created_at: datetime
    expires_at: datetime
    version: int = 1
    booking_code: str | None = None
    failure_reason: str | None = None
    amount: Decimal | None = None
    currency: str | None = None

    def __post_init__(self) -> None:
        _required(self.id, 64, "Reservation ID")
        _required(self.flight_id, 64, "Flight ID")
        _required(self.seat_number, 8, "Seat number")
        _aware(self.created_at)
        _aware(self.expires_at)
        if self.expires_at <= self.created_at or self.version < 1:
            raise ValueError("Expiry must follow creation and version must be positive")
        if (self.amount is None) != (self.currency is None):
            raise ValueError("Price amount and currency must be provided together")
        if self.amount is not None:
            if self.amount <= 0 or self.currency is None:
                raise ValueError("Price snapshot must be positive and include currency")
            _required(self.currency, 3, "Currency")
            if len(self.currency) != 3 or not self.currency.isalpha():
                raise ValueError("Currency must be a three-letter code")
        if self.status is ReservationStatus.CONFIRMED:
            if self.booking_code is None or self.failure_reason is not None:
                raise ValueError("A confirmed reservation requires a booking code")
            _required(self.booking_code, 32, "Booking code")
        elif self.status is ReservationStatus.FAILED:
            if self.failure_reason is None or self.booking_code is not None:
                raise ValueError("A failed reservation requires a failure reason")
            _required(self.failure_reason, 64, "Failure reason")
        elif self.booking_code is not None or self.failure_reason is not None:
            raise ValueError("Pending/expired reservations cannot have an outcome")

    @classmethod
    def start(
        cls,
        reservation_id: str,
        flight_id: str,
        seat_number: str,
        now: datetime,
        expires_at: datetime,
        *,
        amount: Decimal | None = None,
        currency: str | None = None,
    ) -> "Reservation":
        return cls(
            reservation_id,
            flight_id,
            seat_number,
            ReservationStatus.PENDING,
            now,
            expires_at,
            amount=amount,
            currency=currency,
        )

    def confirm(
        self,
        now: datetime,
        *,
        booking_code: str,
        seat_booked: bool,
        payment_captured: bool,
    ) -> "Reservation":
        _aware(now)
        _required(booking_code, 32, "Booking code")
        if (
            self.status is ReservationStatus.CONFIRMED
            and self.booking_code == booking_code
        ):
            return self
        if (
            self.status is not ReservationStatus.PENDING
            or now >= self.expires_at
            or not seat_booked
            or not payment_captured
        ):
            raise ReservationConflict(
                "Cannot confirm without a booked seat and captured payment before expiry"
            )
        return replace(
            self, status=ReservationStatus.CONFIRMED, booking_code=booking_code
        )

    def fail(self, reason: str, *, compensation_resolved: bool) -> "Reservation":
        _required(reason, 64, "Failure reason")
        if self.status is ReservationStatus.FAILED and self.failure_reason == reason:
            return self
        if self.status is not ReservationStatus.PENDING or not compensation_resolved:
            raise ReservationConflict(
                "Cannot fail while compensation remains unresolved"
            )
        return replace(self, status=ReservationStatus.FAILED, failure_reason=reason)

    def expire(self, now: datetime) -> "Reservation":
        _aware(now)
        if self.status is not ReservationStatus.PENDING or now < self.expires_at:
            return self
        return replace(self, status=ReservationStatus.EXPIRED)


@dataclass(frozen=True)
class ReservationSaga:
    reservation_id: str
    correlation_id: str
    step: SagaStep = SagaStep.HOLD_REQUESTED
    compensation_status: CompensationStatus = CompensationStatus.NONE
    payment_attempt_ref: str | None = None

    def __post_init__(self) -> None:
        _required(self.reservation_id, 64, "Reservation ID")
        _required(self.correlation_id, 64, "Correlation ID")
        if self.payment_attempt_ref is not None:
            _required(self.payment_attempt_ref, 64, "Payment attempt reference")
        if (
            self.step is SagaStep.COMPENSATION_PENDING
            and self.compensation_status is not CompensationStatus.PENDING
        ):
            raise ValueError(
                "A pending compensation step must track pending compensation"
            )

    @classmethod
    def start(cls, reservation_id: str, correlation_id: str) -> "ReservationSaga":
        return cls(reservation_id, correlation_id)

    def advance(self, step: SagaStep) -> "ReservationSaga":
        if step is self.step:
            return self
        if step not in _NEXT_STEPS[self.step]:
            raise ReservationConflict(f"Cannot advance saga from {self.step} to {step}")
        status = self.compensation_status
        if step is SagaStep.COMPENSATION_PENDING:
            status = CompensationStatus.PENDING
        elif self.step is SagaStep.COMPENSATION_PENDING and step is SagaStep.DONE:
            status = CompensationStatus.RESOLVED
        return replace(self, step=step, compensation_status=status)


@dataclass(frozen=True)
class ReservationAggregate:
    reservation: Reservation
    saga: ReservationSaga

    def __post_init__(self) -> None:
        if self.reservation.id != self.saga.reservation_id:
            raise ValueError("Saga and reservation must have the same identity")
        if (
            self.reservation.status
            in (
                ReservationStatus.CONFIRMED,
                ReservationStatus.FAILED,
            )
            and self.saga.step is not SagaStep.DONE
        ):
            raise ValueError(
                "A confirmed or failed reservation requires a completed saga"
            )
        if (
            self.reservation.status is ReservationStatus.EXPIRED
            and self.saga.step not in (SagaStep.COMPENSATION_PENDING, SagaStep.DONE)
        ):
            raise ValueError("An expired reservation must track its compensation")
        if (
            self.reservation.status is ReservationStatus.PENDING
            and self.saga.step is SagaStep.DONE
        ):
            raise ValueError("A pending reservation cannot have a completed saga")
