import asyncio
from datetime import date, time
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_booking.modules.inventory.adapters.persistence.models import (
    AirlineRecord,
    AirportRecord,
    Base,
    CityRecord,
    CurrencyRecord,
    FlightRecord,
)
from flight_booking.modules.inventory.adapters.persistence.repository import (
    SqlAlchemyFlightPriceRepository,
)


def test_inventory_price_query_returns_server_price_and_rejects_cancelled_flights():
    async def exercise():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(engine.sync_engine, "connect")
        def attach_schema(connection, _record):
            connection.execute("ATTACH DATABASE ':memory:' AS inventory")

        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            city_id, airline_id = uuid4().hex, uuid4().hex
            async with sessions() as session, session.begin():
                session.add_all(
                    [
                        CityRecord(id=city_id, name="Bogota", country_code="CO"),
                        AirlineRecord(id=airline_id, name="AeroAndes"),
                        CurrencyRecord(
                            code="COP", name="Colombian Peso", minor_unit=0
                        ),
                    ]
                )
                session.add_all(
                    [
                        AirportRecord(iata_code="BOG", city_id=city_id),
                        AirportRecord(iata_code="MDE", city_id=city_id),
                    ]
                )
                session.add_all(
                    [
                        FlightRecord(
                            id="flight-saleable",
                            airline_id=airline_id,
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
                            id="flight-cancelled",
                            airline_id=airline_id,
                            flight_number="AA 205",
                            origin_airport_code="BOG",
                            destination_airport_code="MDE",
                            departure_date=date(2026, 11, 19),
                            origin_time=time(9, 10),
                            destination_time=time(10, 5),
                            duration_minutes=55,
                            price_minor_units=189900,
                            currency_code="COP",
                            status="CANCELLED",
                        ),
                    ]
                )

            async with sessions() as session:
                query = SqlAlchemyFlightPriceRepository(session)
                price = await query.get_price("flight-saleable")
                assert price is not None
                assert price.amount == Decimal(189900)
                assert price.currency == "COP"
                assert await query.get_price("flight-cancelled") is None
                assert await query.get_price("unknown") is None
        finally:
            await engine.dispose()

    asyncio.run(exercise())
