import asyncio
from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_booking.modules.inventory.adapters.persistence.models import (
    Base,
    FlightSeatRecord,
)

seed_script = Path(__file__).parents[1] / "scripts" / "seed_demo_flights.py"
seed_spec = spec_from_file_location("seed_demo_flights", seed_script)
assert seed_spec is not None and seed_spec.loader is not None
seed_demo_flights = module_from_spec(seed_spec)
seed_spec.loader.exec_module(seed_demo_flights)


def test_demo_seed_reconciles_scenarios_without_overwriting_real_seat_holds(
    monkeypatch,
):
    async def exercise():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(engine.sync_engine, "connect")
        def attach_schema(connection, _record):
            connection.execute("ATTACH DATABASE ':memory:' AS inventory")

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(seed_demo_flights, "SessionFactory", sessions)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)

            await seed_demo_flights.main()
            async with sessions() as session, session.begin():
                held = await session.get(FlightSeatRecord, ("flight-204", "4A"))
                booked = await session.get(FlightSeatRecord, ("flight-204", "4B"))
                assert held is not None and held.status == "HELD"
                assert held.held_for_reservation_id == "demo-hold-flight-204-4A"
                assert held.hold_expires_at is not None
                assert booked is not None and booked.status == "BOOKED"

                real_expiry = datetime.now(UTC) + timedelta(minutes=5)
                await session.execute(
                    update(FlightSeatRecord)
                    .where(
                        FlightSeatRecord.flight_id == "flight-204",
                        FlightSeatRecord.seat_number == "2A",
                    )
                    .values(
                        status="HELD",
                        held_for_reservation_id="real-reservation",
                        hold_expires_at=real_expiry,
                    )
                )

            await seed_demo_flights.main()
            async with sessions() as session:
                seats = list(
                    await session.scalars(
                        select(FlightSeatRecord).where(
                            FlightSeatRecord.flight_id == "flight-204"
                        )
                    )
                )
                assert sum(seat.status == "AVAILABLE" for seat in seats) == 17
                assert sum(seat.status == "HELD" for seat in seats) == 2
                assert sum(seat.status == "BOOKED" for seat in seats) == 1

                real_hold = await session.get(FlightSeatRecord, ("flight-204", "2A"))
                assert real_hold is not None
                assert real_hold.status == "HELD"
                assert real_hold.held_for_reservation_id == "real-reservation"

                sold_out = list(
                    await session.scalars(
                        select(FlightSeatRecord).where(
                            FlightSeatRecord.flight_id == "flight-410"
                        )
                    )
                )
                assert len(sold_out) == 36
                assert all(seat.status == "UNAVAILABLE" for seat in sold_out)
        finally:
            await engine.dispose()

    asyncio.run(exercise())
