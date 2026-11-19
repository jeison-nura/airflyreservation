"""Opt-in concurrency check on migrated local PostgreSQL using only test-owned rows."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete

from flight_booking.modules.reservations.adapters.persistence.models import (
    ReservationRecord,
)
from flight_booking.modules.reservations.adapters.persistence.repository import (
    SqlAlchemyReservationRepository,
)
from flight_booking.modules.reservations.adapters.persistence.session import (
    SessionFactory,
)
from flight_booking.modules.reservations.application.ports import (
    ConcurrentReservationWrite,
)
from flight_booking.modules.reservations.domain.models import (
    Reservation,
    ReservationAggregate,
    ReservationSaga,
    ReservationStatus,
    SagaStep,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_RESERVATIONS_POSTGRES_TESTS") != "1",
    reason="Requires an explicitly migrated local PostgreSQL database",
)


def test_confirmation_and_expiry_compete_on_reservation_version():
    async def exercise():
        reservation_id = "test-" + uuid4().hex
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=5)
        repository = SqlAlchemyReservationRepository(SessionFactory)
        original = ReservationAggregate(
            Reservation.start(reservation_id, "test-flight", "1A", now, expires_at),
            ReservationSaga.start(reservation_id, uuid4().hex),
        )
        try:
            await repository.create(original)
            confirmed = ReservationAggregate(
                original.reservation.confirm(
                    now,
                    booking_code=uuid4().hex,
                    seat_booked=True,
                    payment_captured=True,
                ),
                original.saga.advance(SagaStep.HOLD_OBTAINED)
                .advance(SagaStep.AUTHORIZING)
                .advance(SagaStep.AUTHORIZED)
                .advance(SagaStep.BOOKING_SEAT)
                .advance(SagaStep.SEAT_BOOKED)
                .advance(SagaStep.CAPTURING)
                .advance(SagaStep.DONE),
            )
            expired = ReservationAggregate(
                original.reservation.expire(expires_at),
                original.saga.advance(SagaStep.COMPENSATION_PENDING),
            )
            outcomes = await asyncio.gather(
                repository.save(confirmed, expected_version=1),
                repository.save(expired, expected_version=1),
                return_exceptions=True,
            )
            assert (
                sum(
                    isinstance(result, ConcurrentReservationWrite)
                    for result in outcomes
                )
                == 1
            )
            persisted = await repository.get(reservation_id)
            assert persisted.reservation.version == 2
            assert persisted.reservation.status in {
                ReservationStatus.CONFIRMED,
                ReservationStatus.EXPIRED,
            }
            if persisted.reservation.status is ReservationStatus.CONFIRMED:
                assert persisted.saga.step is SagaStep.DONE
            else:
                assert persisted.saga.step is SagaStep.COMPENSATION_PENDING
        finally:
            async with SessionFactory() as session, session.begin():
                await session.execute(
                    delete(ReservationRecord).where(
                        ReservationRecord.id == reservation_id
                    )
                )

    asyncio.run(exercise())
