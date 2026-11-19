"""Create an authorized, time-limited reservation and request its inventory hold."""

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import uuid4

from flight_booking.modules.reservations.application.ports import (
    FlightPricing,
    InventoryCommands,
    ReservationBookingRepository,
)
from flight_booking.modules.reservations.domain.models import (
    Reservation,
    ReservationAggregate,
    ReservationSaga,
    SagaStep,
)
from flight_booking.shared.observability import log_event


class ReservationClock(Protocol):
    def now(self) -> datetime: ...


class SeatUnavailable(Exception):
    """The requested seat cannot be held."""


class SeatDoesNotExist(Exception):
    """The flight or seat does not exist."""


@dataclass(frozen=True)
class CreateReservationResult:
    aggregate: ReservationAggregate
    access_token: str | None
    replayed: bool


class CreateReservation:
    def __init__(
        self,
        repository: ReservationBookingRepository,
        inventory: InventoryCommands,
        pricing: FlightPricing,
        clock: ReservationClock,
        *,
        hold_ttl: timedelta = timedelta(minutes=10),
    ) -> None:
        self._repository = repository
        self._inventory = inventory
        self._pricing = pricing
        self._clock = clock
        self._hold_ttl = hold_ttl

    async def execute(
        self,
        *,
        flight_id: str,
        seat_number: str,
        full_name: str,
        email: str,
        idempotency_key: str,
    ) -> CreateReservationResult:
        request_hash = hashlib.sha256(
            json.dumps(
                {
                    "flightId": flight_id,
                    "seatNumber": seat_number,
                    "passenger": {"fullName": full_name, "email": email},
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        quote = await self._pricing.quote(flight_id)
        if quote is None:
            raise SeatDoesNotExist
        now = self._clock.now()
        reservation_id = uuid4().hex
        correlation_id = uuid4().hex
        reservation = Reservation.start(
            reservation_id,
            flight_id,
            seat_number,
            now,
            now + self._hold_ttl,
            amount=quote.amount,
            currency=quote.currency,
        )
        aggregate = ReservationAggregate(
            reservation, ReservationSaga.start(reservation_id, correlation_id)
        )
        access_token = secrets.token_urlsafe(32)
        aggregate, replayed = await self._repository.create_booking(
            aggregate,
            full_name=full_name,
            email=email,
            access_credential_hash=hashlib.sha256(access_token.encode()).hexdigest(),
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if replayed and aggregate.saga.step is SagaStep.HOLD_REQUESTED:
            # Recover the hold if the original process stopped after persisting intent.
            aggregate = await self._request_hold(aggregate)
        elif not replayed:
            aggregate = await self._request_hold(aggregate)
        log_event(
            "reservations", "reservation_created", correlation_id=aggregate.saga.correlation_id,
            status=aggregate.reservation.status.value, replayed=replayed,
        )
        return CreateReservationResult(
            aggregate=aggregate,
            access_token=None if replayed else access_token,
            replayed=replayed,
        )

    async def _request_hold(
        self, aggregate: ReservationAggregate
    ) -> ReservationAggregate:
        reservation = aggregate.reservation
        try:
            await self._inventory.hold(
                reservation.flight_id,
                reservation.seat_number,
                reservation.id,
                reservation.expires_at,
                correlation_id=aggregate.saga.correlation_id,
            )
        except SeatDoesNotExist:
            await self._mark_failed(aggregate, "HOLD_REJECTED")
            raise
        except SeatUnavailable:
            await self._mark_failed(aggregate, "HOLD_REJECTED")
            raise
        changed = ReservationAggregate(
            reservation,
            aggregate.saga.advance(SagaStep.HOLD_OBTAINED),
        )
        return await self._repository.save(
            changed, expected_version=reservation.version
        )

    async def _mark_failed(self, aggregate: ReservationAggregate, reason: str) -> None:
        failed = ReservationAggregate(
            aggregate.reservation.fail(reason, compensation_resolved=True),
            aggregate.saga.advance(SagaStep.DONE),
        )
        await self._repository.save(
            failed, expected_version=aggregate.reservation.version
        )
        log_event(
            "reservations", "reservation_hold_rejected", level="WARNING",
            correlation_id=aggregate.saga.correlation_id, outcome=reason,
        )
