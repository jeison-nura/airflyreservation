"""Opt-in real PostgreSQL checks; create and remove only test-owned rows."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_booking.modules.inventory.adapters.persistence.models import (
    CommandIdempotencyRecord,
    FlightRecord,
    FlightSeatRecord,
    OutboxEventRecord,
)
from flight_booking.modules.inventory.adapters.persistence.repository import (
    SqlAlchemySeatMutationRepository,
)
from flight_booking.modules.inventory.adapters.persistence.session import (
    DATABASE_URL,
    SessionFactory,
)
from flight_booking.modules.inventory.adapters.persistence.worker_repository import (
    SqlAlchemyOutboxRepository,
)
from flight_booking.modules.inventory.application.expire_due_holds import ExpireDueHolds
from flight_booking.modules.inventory.application.ports import CommandContext
from flight_booking.modules.inventory.domain.models import SeatStatus
from flight_booking.modules.inventory.domain.seat_allocation import SeatConflict
from flight_booking.modules.payments.adapters.commands import SqlAlchemyPaymentCommands
from flight_booking.modules.payments.adapters.persistence.models import (
    PaymentAttemptRecord,
)
from flight_booking.modules.reservations.adapters.inventory import (
    InventoryCommandsAdapter,
    InventoryFlightPricingAdapter,
)
from flight_booking.modules.reservations.adapters.persistence.models import (
    ReservationRecord,
)
from flight_booking.modules.reservations.adapters.persistence.repository import (
    SqlAlchemyReservationRepository,
)
from flight_booking.modules.reservations.adapters.worker import tasks
from flight_booking.modules.reservations.application.confirm_reservation import (
    ConfirmReservation,
    PaymentUnavailable,
)
from flight_booking.modules.reservations.application.create_reservation import (
    CreateReservation,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INVENTORY_POSTGRES_TESTS") != "1",
    reason="Requires a local migrated PostgreSQL database and demo seed",
)


def test_concurrent_idempotency_expiry_and_outbox_on_postgres():
    async def exercise():
        flight_id = "test-" + uuid4().hex
        key = uuid4().hex
        conflict_key = uuid4().hex
        async with SessionFactory() as session:
            source = await session.get(FlightRecord, "flight-204")
            if source is None:
                pytest.skip("Seed flight-204 not available")
            session.add(replace_flight(source, flight_id))
            session.add(
                FlightSeatRecord(
                    flight_id=flight_id, seat_number="1A", status="AVAILABLE"
                )
            )
            await session.commit()
        try:
            repository = SqlAlchemySeatMutationRepository(SessionFactory)
            now = datetime.now(UTC)
            expiration = now + timedelta(minutes=1)
            context = CommandContext("hold", key, "a" * 64, uuid4().hex, uuid4().hex)

            async def hold(owner, command):
                try:
                    return await repository.mutate(
                        flight_id,
                        "1A",
                        lambda seat: seat.hold(owner, expiration, now),
                        context=command,
                    )
                except SeatConflict:
                    return "conflict"

            same_key = await asyncio.gather(
                hold("reservation-1", context),
                hold("reservation-1", context),
            )
            assert same_key[0] == same_key[1]
            assert same_key[0].status is SeatStatus.HELD
            other = await hold(
                "reservation-2",
                CommandContext(
                    "hold", conflict_key, "b" * 64, uuid4().hex, uuid4().hex
                ),
            )
            assert other == "conflict"

            class LaterClock:
                def now(self):
                    return expiration + timedelta(seconds=1)

            class TestCandidates:
                async def find_due(self, now, limit):
                    return [(flight_id, "1A")]

            worker = ExpireDueHolds(TestCandidates(), repository, LaterClock())
            assert await worker.run_once(limit=1) == 1
            assert (
                await repository.mutate(
                    flight_id,
                    "1A",
                    lambda seat: (_ for _ in ()).throw(
                        AssertionError("replayed transition")
                    ),
                    context=context,
                )
            ).status is SeatStatus.HELD
            async with SessionFactory() as session:
                seat = await session.get(FlightSeatRecord, (flight_id, "1A"))
                events = (
                    await session.scalars(
                        select(OutboxEventRecord).where(
                            OutboxEventRecord.flight_id == flight_id
                        )
                    )
                ).all()
                assert seat.status == "AVAILABLE"
                assert [event.event_type for event in events] == [
                    "SeatHeld",
                    "SeatHoldExpired",
                ]
                assert all(event.delivered_at is None for event in events)
            outbox = SqlAlchemyOutboxRepository(SessionFactory)
            claimed = await asyncio.gather(
                outbox.claim(
                    "consumer-1", datetime.now(UTC), limit=1, lease_seconds=30
                ),
                outbox.claim(
                    "consumer-2", datetime.now(UTC), limit=1, lease_seconds=30
                ),
            )
            assert len(claimed[0]) == len(claimed[1]) == 1
            assert claimed[0][0].id != claimed[1][0].id
            assert await outbox.ack(
                claimed[0][0].id,
                "consumer-1",
                datetime.now(UTC),
                claim_token=claimed[0][0].claim_token,
            )
        finally:
            async with SessionFactory() as session, session.begin():
                await session.execute(
                    delete(OutboxEventRecord).where(
                        OutboxEventRecord.flight_id == flight_id
                    )
                )
                await session.execute(
                    delete(CommandIdempotencyRecord).where(
                        CommandIdempotencyRecord.operation == "hold",
                        CommandIdempotencyRecord.key.in_([key, conflict_key]),
                    )
                )
                flight = await session.get(FlightRecord, flight_id)
                if flight is not None:
                    await session.delete(flight)

    asyncio.run(exercise())


def replace_flight(source: FlightRecord, flight_id: str) -> FlightRecord:
    return FlightRecord(
        id=flight_id,
        airline_id=source.airline_id,
        flight_number="TEST",
        origin_airport_code=source.origin_airport_code,
        destination_airport_code=source.destination_airport_code,
        departure_date=source.departure_date,
        origin_time=source.origin_time,
        destination_time=source.destination_time,
        duration_minutes=source.duration_minutes,
        price_minor_units=source.price_minor_units,
        currency_code=source.currency_code,
        status=source.status,
    )


def test_expiry_worker_voids_unpaid_booking_and_keeps_confirmed_booking(monkeypatch):
    async def exercise():
        engine = create_async_engine(DATABASE_URL, hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        ids = set()
        flight_id = f"test-{uuid4().hex}"
        now = datetime.now(UTC)

        class PurchaseClock:
            def now(self):
                return now

        class ExpiryClock:
            def now(self):
                return now + timedelta(minutes=11)

        class InterruptedPayments(SqlAlchemyPaymentCommands):
            async def capture(self, **_kwargs):
                raise PaymentUnavailable

        class TestReservations(SqlAlchemyReservationRepository):
            async def find_due(self, instant, limit):
                candidates = await super().find_due(instant, limit)
                return [reservation_id for reservation_id in candidates if reservation_id in ids]

        monkeypatch.setattr(tasks, "SystemClock", ExpiryClock)
        monkeypatch.setattr(tasks, "SqlAlchemyReservationRepository", TestReservations)
        try:
            async with sessions() as session, session.begin():
                source = await session.get(FlightRecord, "flight-204")
                if source is None:
                    pytest.skip("Seed flight-204 not available")
                session.add(replace_flight(source, flight_id))
                session.add_all(
                    FlightSeatRecord(flight_id=flight_id, seat_number=seat, status="AVAILABLE")
                    for seat in ("1A", "1B")
                )

            repository = SqlAlchemyReservationRepository(sessions)
            inventory = InventoryCommandsAdapter(sessions)
            payments = SqlAlchemyPaymentCommands(sessions)
            create = CreateReservation(
                repository, inventory, InventoryFlightPricingAdapter(sessions), PurchaseClock()
            )

            async def purchase(seat_number, adapter):
                result = await create.execute(
                    flight_id=flight_id,
                    seat_number=seat_number,
                    full_name="Test Passenger",
                    email="worker@example.test",
                    idempotency_key=uuid4().hex,
                )
                reservation_id = result.aggregate.reservation.id
                ids.add(reservation_id)
                return await ConfirmReservation(
                    repository, inventory, adapter, PurchaseClock()
                ).execute(reservation_id, idempotency_key=uuid4().hex)

            unpaid = await purchase("1A", InterruptedPayments(sessions))
            paid = await purchase("1B", payments)
            assert unpaid.pending is True
            assert paid.aggregate.reservation.status == "CONFIRMED"
            async with sessions() as session:
                assert (await session.get(FlightSeatRecord, (flight_id, "1A"))).status == "BOOKED"

            assert await tasks.expire_due_reservations_batch() == 2
            assert await tasks.expire_due_reservations_batch() == 0
            expired = await repository.get(unpaid.aggregate.reservation.id)
            confirmed = await repository.get(paid.aggregate.reservation.id)
            assert expired is not None and confirmed is not None
            assert expired.reservation.status == "EXPIRED"
            assert expired.saga.step == "DONE"
            assert confirmed.reservation.status == "CONFIRMED"
            async with sessions() as session:
                assert (await session.get(FlightSeatRecord, (flight_id, "1A"))).status == "AVAILABLE"
                assert (await session.get(FlightSeatRecord, (flight_id, "1B"))).status == "BOOKED"
                attempt = await session.get(PaymentAttemptRecord, expired.saga.payment_attempt_ref)
                assert attempt.status == "VOIDED"
                captured = await session.get(
                    PaymentAttemptRecord, confirmed.saga.payment_attempt_ref
                )
                assert captured.status == "CAPTURED"
        finally:
            async with sessions() as session, session.begin():
                await session.execute(
                    delete(OutboxEventRecord).where(OutboxEventRecord.flight_id == flight_id)
                )
                command_keys = [
                    f"reservation-{reservation_id}-{operation}"
                    for reservation_id in ids
                    for operation in ("hold", "confirm", "release")
                ]
                await session.execute(
                    delete(CommandIdempotencyRecord).where(
                        CommandIdempotencyRecord.key.in_(command_keys)
                    )
                )
                await session.execute(
                    delete(PaymentAttemptRecord).where(PaymentAttemptRecord.reservation_id.in_(ids))
                )
                await session.execute(
                    delete(ReservationRecord).where(ReservationRecord.id.in_(ids))
                )
                await session.execute(
                    delete(FlightRecord).where(FlightRecord.id == flight_id)
                )
            await engine.dispose()

    asyncio.run(exercise())
