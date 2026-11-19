import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_booking.modules.reservations.adapters.persistence.models import Base
from flight_booking.modules.reservations.adapters.persistence.repository import (
    ConcurrentReservationWrite,
    ReservationWriteConflict,
    SqlAlchemyReservationRepository,
)
from flight_booking.modules.reservations.domain.models import (
    Reservation,
    ReservationAggregate,
    ReservationConflict,
    ReservationSaga,
    ReservationStatus,
    SagaStep,
)

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)
EXPIRES = NOW + timedelta(minutes=10)


def aggregate(reservation_id: str = "reservation-1") -> ReservationAggregate:
    return ReservationAggregate(
        Reservation.start(reservation_id, "flight-204", "1A", NOW, EXPIRES),
        ReservationSaga.start(reservation_id, "correlation-1"),
    )


def test_create_load_and_versioned_save_are_atomic():
    async def exercise():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(engine.sync_engine, "connect")
        def attach_schema(connection, _record):
            connection.execute("ATTACH DATABASE ':memory:' AS reservations")

        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            repository = SqlAlchemyReservationRepository(
                async_sessionmaker(engine, expire_on_commit=False)
            )
            assert await repository.get("unknown") is None
            original = aggregate()
            assert await repository.create(original) == original
            assert await repository.get(original.reservation.id) == original

            changed = ReservationAggregate(
                original.reservation.confirm(
                    NOW + timedelta(minutes=1),
                    booking_code="CODE-1",
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
            saved = await repository.save(changed, expected_version=1)
            assert saved.reservation.version == 2
            assert saved.reservation.status is ReservationStatus.CONFIRMED
            assert await repository.get(original.reservation.id) == saved

            with pytest.raises(ConcurrentReservationWrite):
                await repository.save(
                    ReservationAggregate(
                        original.reservation.expire(EXPIRES),
                        original.saga.advance(SagaStep.COMPENSATION_PENDING),
                    ),
                    expected_version=1,
                )
            assert await repository.get(original.reservation.id) == saved

            with pytest.raises(ReservationWriteConflict):
                await repository.create(aggregate())
            second = aggregate("reservation-2")
            assert await repository.create(second) == second
            duplicate_code = ReservationAggregate(
                second.reservation.confirm(
                    NOW + timedelta(minutes=1),
                    booking_code="CODE-1",
                    seat_booked=True,
                    payment_captured=True,
                ),
                ReservationSaga(
                    second.reservation.id, second.saga.correlation_id, SagaStep.DONE
                ),
            )
            with pytest.raises(ReservationWriteConflict):
                await repository.save(duplicate_code, expected_version=1)
            assert await repository.get(second.reservation.id) == second
            with pytest.raises(ValueError):
                await repository.save(
                    ReservationAggregate(
                        Reservation.start(
                            "reservation-2", "flight-changed", "1A", NOW, EXPIRES
                        ),
                        second.saga,
                    ),
                    expected_version=1,
                )
            third = aggregate("reservation-3")
            await repository.create(third)
            expired = await repository.save(
                ReservationAggregate(
                    third.reservation.expire(EXPIRES),
                    third.saga.advance(SagaStep.COMPENSATION_PENDING),
                ),
                expected_version=1,
            )
            with pytest.raises(ReservationConflict):
                await repository.save(
                    ReservationAggregate(
                        replace(expired.reservation, status=ReservationStatus.PENDING),
                        expired.saga,
                    ),
                    expected_version=expired.reservation.version,
                )
            with pytest.raises(ReservationConflict):
                await repository.save(
                    ReservationAggregate(
                        replace(saved.reservation, booking_code="OTHER-CODE"),
                        saved.saga,
                    ),
                    expected_version=saved.reservation.version,
                )
            assert await repository.get(saved.reservation.id) == saved
        finally:
            await engine.dispose()

    asyncio.run(exercise())
