"""Reservation persistence contract, independent of SQLAlchemy."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from flight_booking.modules.reservations.domain.models import ReservationAggregate


class ReservationWriteConflict(Exception):
    """A reservation identity or booking code is already in use."""


class ConcurrentReservationWrite(Exception):
    """The aggregate has changed since the caller read it."""


class ReservationNotFound(Exception):
    """The reservation no longer exists."""


class IdempotencyKeyConflict(Exception):
    """An idempotency key was reused with a different request."""


class ReservationRepository(Protocol):
    async def create(self, aggregate: ReservationAggregate) -> ReservationAggregate: ...

    async def get(self, reservation_id: str) -> ReservationAggregate | None: ...

    async def save(
        self, aggregate: ReservationAggregate, *, expected_version: int
    ) -> ReservationAggregate:
        """Commit reservation outcome and saga progress as one local transaction.

        Raise ConcurrentReservationWrite if expected_version is no longer current.
        The returned aggregate carries the next version; nothing writes outside
        the reservations schema.
        """
        ...

    async def find_due(self, now: datetime, limit: int) -> list[str]: ...

    async def claim_idempotency(
        self,
        operation: str,
        key: str,
        request_hash: str,
        reservation_id: str,
        created_at: datetime,
    ) -> bool: ...

    async def get_notifications_after(
        self, reservation_id: str, after_sequence: int, *, limit: int
    ) -> list["ReservationNotification"]: ...

    async def get_notification_sequence(self, reservation_id: str) -> int: ...


@dataclass(frozen=True)
class ReservationNotification:
    notification_id: str
    sequence: int
    status: str
    occurred_at: datetime


class ReservationBookingRepository(ReservationRepository, Protocol):
    async def create_booking(
        self,
        aggregate: ReservationAggregate,
        *,
        full_name: str,
        email: str,
        access_credential_hash: str,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[ReservationAggregate, bool]: ...

    async def get_access_credential_hash(self, reservation_id: str) -> str | None: ...


class InventoryCommands(Protocol):
    async def hold(
        self,
        flight_id: str,
        seat_number: str,
        reservation_id: str,
        expires_at: datetime,
        *,
        correlation_id: str,
    ) -> None: ...

    async def confirm(
        self,
        flight_id: str,
        seat_number: str,
        reservation_id: str,
        *,
        correlation_id: str,
    ) -> None: ...

    async def release(
        self,
        flight_id: str,
        seat_number: str,
        reservation_id: str,
        *,
        correlation_id: str,
    ) -> None: ...


@dataclass(frozen=True)
class FlightQuote:
    amount: Decimal
    currency: str


class FlightPricing(Protocol):
    async def quote(self, flight_id: str) -> FlightQuote | None: ...


@dataclass(frozen=True)
class PaymentResult:
    status: Literal[
        "AUTHORIZED", "DENIED", "CAPTURED", "VOIDED", "REFUNDED", "UNKNOWN"
    ]
    payment_attempt_ref: str
    failure_code: str | None = None


class PaymentCommands(Protocol):
    async def authorize(
        self,
        *,
        payment_attempt_ref: str,
        reservation_id: str,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> PaymentResult: ...

    async def capture(
        self,
        *,
        payment_attempt_ref: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> PaymentResult: ...

    async def query_attempt(
        self, *, payment_attempt_ref: str, correlation_id: str
    ) -> PaymentResult: ...

    async def void(
        self,
        *,
        payment_attempt_ref: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> PaymentResult: ...

    async def refund(
        self,
        *,
        payment_attempt_ref: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> PaymentResult: ...
