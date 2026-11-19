import asyncio
import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_booking.modules.inventory.adapters.persistence.models import (
    AirlineRecord,
    AirportRecord,
    Base,
    CityRecord,
    CommandIdempotencyRecord,
    CurrencyRecord,
    FlightRecord,
    FlightSeatRecord,
    OutboxEventRecord,
)
from flight_booking.modules.inventory.adapters.persistence.repository import (
    IdempotencyKeyConflict,
    SqlAlchemyFlightRepository,
    SqlAlchemyFlightSeatRepository,
    SqlAlchemySeatMutationRepository,
)
from flight_booking.modules.inventory.adapters.persistence.worker_repository import (
    SqlAlchemyExpiredSeatRepository,
    SqlAlchemyOutboxRepository,
)
from flight_booking.modules.inventory.application.expire_due_holds import ExpireDueHolds
from flight_booking.modules.inventory.application.ports import CommandContext
from flight_booking.modules.inventory.domain.models import FlightStatus, SeatStatus


def test_repository_joins_catalog_and_counts_available_seats_per_flight(capsys):
    async def exercise_repository():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(engine.sync_engine, "connect")
        def attach_inventory_schema(connection, _record):
            connection.execute("ATTACH DATABASE ':memory:' AS inventory")

        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            session.add_all(
                [
                    CityRecord(
                        id="11111111-1111-4111-8111-111111111111",
                        name="Bogotá",
                        country_code="CO",
                    ),
                    CityRecord(
                        id="22222222-2222-4222-8222-222222222222",
                        name="Medellín",
                        country_code="CO",
                    ),
                    AirlineRecord(id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", name="AeroAndes"),
                    CurrencyRecord(code="COP", name="Colombian peso", minor_unit=0),
                    CurrencyRecord(code="USD", name="US dollar", minor_unit=2),
                ]
            )
            session.add_all(
                [
                    AirportRecord(
                        iata_code="BOG",
                        city_id="11111111-1111-4111-8111-111111111111",
                    ),
                    AirportRecord(
                        iata_code="MDE",
                        city_id="22222222-2222-4222-8222-222222222222",
                    ),
                ]
            )
            session.add_all(
                [
                    FlightRecord(
                        id="flight-late",
                        airline_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                        flight_number="AA 318",
                        origin_airport_code="BOG",
                        destination_airport_code="MDE",
                        departure_date=date(2026, 11, 19),
                        origin_time=time(10, 35),
                        destination_time=time(11, 30),
                        duration_minutes=55,
                        price_minor_units=214500,
                        currency_code="USD",
                        status="ON_TIME",
                    ),
                    FlightRecord(
                        id="flight-early",
                        airline_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                        flight_number="AA 204",
                        origin_airport_code="BOG",
                        destination_airport_code="MDE",
                        departure_date=date(2026, 11, 19),
                        origin_time=time(7, 10),
                        destination_time=time(8, 5),
                        duration_minutes=55,
                        price_minor_units=189900,
                        currency_code="COP",
                        status="ON_TIME",
                    ),
                    FlightRecord(
                        id="flight-other-date",
                        airline_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                        flight_number="AA 204",
                        origin_airport_code="BOG",
                        destination_airport_code="MDE",
                        departure_date=date(2026, 11, 20),
                        origin_time=time(15, 20),
                        destination_time=time(16, 15),
                        duration_minutes=55,
                        price_minor_units=209900,
                        currency_code="COP",
                        status="DELAYED",
                    ),
                ]
            )
            session.add_all(
                [
                    FlightSeatRecord(
                        flight_id="flight-early",
                        seat_number="1A",
                        status="AVAILABLE",
                    ),
                    FlightSeatRecord(
                        flight_id="flight-early",
                        seat_number="1B",
                        status="AVAILABLE",
                    ),
                    FlightSeatRecord(
                        flight_id="flight-early",
                        seat_number="1C",
                        status="BOOKED",
                    ),
                    FlightSeatRecord(
                        flight_id="flight-late",
                        seat_number="1A",
                        status="AVAILABLE",
                    ),
                    FlightSeatRecord(
                        flight_id="flight-late",
                        seat_number="1B",
                        status="HELD",
                        held_for_reservation_id="reservation-1",
                        hold_expires_at=datetime(2026, 11, 19, tzinfo=UTC),
                    ),
                ]
            )
            await session.commit()
            repository = SqlAlchemyFlightRepository(session)

            results = await repository.search(
                origin="BOG",
                destination="MDE",
                departure_date=date(2026, 11, 19),
                page=1,
                page_size=1,
            )
            next_page = await repository.search(
                origin="BOG",
                destination="MDE",
                departure_date=date(2026, 11, 19),
                page=2,
                page_size=1,
            )
            out_of_range = await repository.search(
                origin="BOG",
                destination="MDE",
                departure_date=date(2026, 11, 19),
                page=3,
                page_size=1,
            )
            no_matches = await repository.search(
                origin="MDE",
                destination="BOG",
                departure_date=date(2026, 11, 19),
                page=1,
                page_size=1,
            )
            seat_repository = SqlAlchemyFlightSeatRepository(session)
            early_seats = await seat_repository.get_by_flight("flight-early")
            late_seats = await seat_repository.get_by_flight("flight-late")
            empty_seats = await seat_repository.get_by_flight("flight-other-date")
            unknown_seats = await seat_repository.get_by_flight("flight-unknown")

        mutations = SqlAlchemySeatMutationRepository(session_factory)
        now = datetime(2026, 11, 18, tzinfo=UTC)
        expires_at = datetime(2026, 11, 19, tzinfo=UTC)
        held = await mutations.mutate(
            "flight-early",
            "1A",
            lambda seat: seat.hold("reservation-1", expires_at, now),
        )
        assert held.status is SeatStatus.HELD
        replaced = await mutations.mutate(
            "flight-early", "1A",
            lambda seat: seat.hold(
                "reservation-replacement", expires_at + timedelta(minutes=1),
                expires_at + timedelta(seconds=1),
            ),
        )
        assert replaced.reservation_id == "reservation-replacement"
        async with session_factory() as check_session:
            replacement_events = (
                await check_session.scalars(
                    select(OutboxEventRecord).where(
                        OutboxEventRecord.flight_id == "flight-early",
                        OutboxEventRecord.seat_number == "1A",
                    )
                )
            ).all()
            assert [event.event_type for event in replacement_events] == [
                "SeatHeld", "SeatHoldReplaced"
            ]
            assert replacement_events[-1].payload["previousReservationId"] == "reservation-1"
        command = CommandContext(
            operation="hold",
            key="same-intent",
            request_hash="a" * 64,
            correlation_id="c" * 32,
            causation_id="command-1",
        )
        held_with_key = await mutations.mutate(
            "flight-early",
            "1B",
            lambda seat: seat.hold("reservation-2", expires_at, now),
            context=command,
        )
        replay = await mutations.mutate(
            "flight-early",
            "1B",
            lambda seat: seat.hold("another-owner", expires_at, now),
            context=command,
        )
        assert replay == held_with_key
        output = capsys.readouterr().out
        records = [json.loads(line) for line in output.splitlines()]
        hold_log = next(record for record in records if record["correlation_id"] == "c" * 32)
        assert hold_log["module"] == "inventory"
        assert hold_log["event"] == "seat_command"
        assert hold_log["operation"] == "hold"
        assert hold_log["status"] == "HELD"
        assert "same-intent" not in output
        assert "reservation-2" not in output
        with pytest.raises(IdempotencyKeyConflict):
            await mutations.mutate(
                "flight-early",
                "1B",
                lambda seat: seat,
                context=CommandContext(
                    operation="hold",
                    key="same-intent",
                    request_hash="b" * 64,
                    correlation_id="correlation-2",
                    causation_id="command-2",
                ),
            )
        with pytest.raises(ValueError):
            await mutations.mutate(
                "flight-early",
                "1B",
                lambda seat: seat.hold("reservation-2", now, now),
            )
        def broken_transition(_seat):
            raise RuntimeError("unexpected adapter failure")

        with pytest.raises(RuntimeError):
            await mutations.mutate(
                "flight-early", "1B", broken_transition,
                context=CommandContext(
                    "release", "will-fail", "c" * 64, "correlation-3", "command-3"
                ),
            )
        async with session_factory() as check_session:
            assert await check_session.get(
                CommandIdempotencyRecord, ("release", "will-fail")
            ) is None
        assert await mutations.mutate("flight-unknown", "1A", lambda seat: seat) is None
        worker_now = expires_at + timedelta(minutes=1, seconds=1)
        candidates = SqlAlchemyExpiredSeatRepository(session_factory)
        due = await candidates.find_due(worker_now, 10)
        assert ("flight-early", "1A") in due

        class FixedClock:
            def now(self):
                return worker_now

        assert await ExpireDueHolds(candidates, mutations, FixedClock()).run_once(limit=10) == 3
        assert await ExpireDueHolds(candidates, mutations, FixedClock()).run_once(limit=10) == 0
        # A replay returns the original outcome even after the worker freed the seat.
        assert (
            await mutations.mutate(
                "flight-early", "1B", lambda seat: seat, context=command
            )
        ) == held_with_key

        outbox = SqlAlchemyOutboxRepository(session_factory)
        claimed = await outbox.claim("consumer-a", worker_now, limit=2, lease_seconds=5)
        assert len(claimed) == 2
        assert await outbox.claim("consumer-b", worker_now, limit=10, lease_seconds=5)
        assert not await outbox.ack(
            claimed[0].id, "consumer-b", worker_now, claim_token=claimed[0].claim_token
        )
        assert not await outbox.ack(
            claimed[0].id, "consumer-a", worker_now + timedelta(seconds=6),
            claim_token=claimed[0].claim_token,
        )
        reclaimed = await outbox.claim(
            "consumer-b", worker_now + timedelta(seconds=6), limit=10, lease_seconds=5
        )
        assert claimed[0].id in {event.id for event in reclaimed}
        renewed = next(event for event in reclaimed if event.id == claimed[0].id)
        assert await outbox.ack(
            claimed[0].id, "consumer-b", worker_now + timedelta(seconds=6),
            claim_token=renewed.claim_token,
        )
        assert not await outbox.ack(
            claimed[0].id, "consumer-b", worker_now + timedelta(seconds=6),
            claim_token=renewed.claim_token,
        )
        # A stale attempt cannot acknowledge a newer lease with the same consumer name.
        await outbox.claim(
            "consumer-b", worker_now + timedelta(seconds=12), limit=10, lease_seconds=5
        )
        assert not await outbox.ack(
            claimed[1].id, "consumer-b", worker_now + timedelta(seconds=12),
            claim_token=claimed[1].claim_token,
        )
        async with session_factory() as check_session:
            events = (await check_session.scalars(select(OutboxEventRecord))).all()
            ledger = await check_session.get(CommandIdempotencyRecord, ("hold", "same-intent"))
            assert len(events) == 6
            assert sum(event.delivered_at is not None for event in events) == 1
            assert ledger.outcome["kind"] == "success"
            held_row = await check_session.get(FlightSeatRecord, ("flight-early", "1A"))
            unchanged_row = await check_session.get(FlightSeatRecord, ("flight-early", "1B"))
            assert held_row.status == "AVAILABLE"
            assert unchanged_row.status == "AVAILABLE"

        await engine.dispose()
        assert [flight.id for flight in results.flights] == ["flight-early"]
        assert [flight.id for flight in next_page.flights] == ["flight-late"]
        assert out_of_range.flights == []
        assert (results.total_items, next_page.total_items, out_of_range.total_items) == (2, 2, 2)
        assert no_matches.flights == []
        assert no_matches.total_items == 0
        assert results.flights[0].available_seats == 2
        assert next_page.flights[0].available_seats == 1
        assert results.flights[0].airline == "AeroAndes"
        assert results.flights[0].origin.city == "Bogotá"
        assert results.flights[0].status is FlightStatus.ON_TIME
        assert next_page.flights[0].price == Decimal(2145)
        assert [(seat.seat_number, seat.status) for seat in early_seats] == [
            ("1A", SeatStatus.AVAILABLE),
            ("1B", SeatStatus.AVAILABLE),
            ("1C", SeatStatus.BOOKED),
        ]
        assert [(seat.seat_number, seat.status) for seat in late_seats] == [
            ("1A", SeatStatus.AVAILABLE),
            ("1B", SeatStatus.HELD),
        ]
        assert empty_seats == []
        assert unknown_seats is None

    asyncio.run(exercise_repository())
