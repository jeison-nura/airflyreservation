import asyncio
import os
from datetime import UTC, date, datetime, time, timedelta

from flight_booking.modules.inventory.adapters.persistence.models import (
    AirlineRecord,
    AirportRecord,
    CityRecord,
    CurrencyRecord,
    FlightRecord,
    FlightSeatRecord,
)
from flight_booking.modules.inventory.adapters.persistence.session import SessionFactory

DEMO_CITIES = {
    "Bogotá": "11111111-1111-4111-8111-111111111111",
    "Medellín": "22222222-2222-4222-8222-222222222222",
    "Cali": "33333333-3333-4333-8333-333333333333",
}
DEMO_AIRPORTS = {
    "BOG": "Bogotá",
    "MDE": "Medellín",
    "CLO": "Cali",
}
DEMO_AIRLINE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SEAT_NUMBERS = [f"{row}{column}" for row in range(1, 7) for column in "ABCDEF"]
DEMO_SEAT_OVERRIDES = {
    ("flight-204", "4A"): ("HELD", "demo-hold-flight-204-4A"),
    ("flight-204", "4B"): ("BOOKED", "demo-booked-flight-204-4B"),
}
DEMO_HOLD_TTL_MINUTES = max(1, int(os.getenv("DEMO_HOLD_TTL_MINUTES", "30")))

DEMO_FLIGHTS = (
    {
        "id": "flight-204",
        "flight_number": "AA 204",
        "origin_airport_code": "BOG",
        "destination_airport_code": "MDE",
        "departure_date": date(2026, 11, 19),
        "origin_time": time(7, 10),
        "destination_time": time(8, 5),
        "duration_minutes": 55,
        "price_minor_units": 189900,
        "available_seats": 18,
        "status": "ON_TIME",
    },
    {
        "id": "flight-318",
        "flight_number": "AA 318",
        "origin_airport_code": "BOG",
        "destination_airport_code": "MDE",
        "departure_date": date(2026, 11, 19),
        "origin_time": time(10, 35),
        "destination_time": time(11, 30),
        "duration_minutes": 55,
        "price_minor_units": 214500,
        "available_seats": 6,
        "status": "ON_TIME",
    },
    {
        "id": "flight-522",
        "flight_number": "AA 522",
        "origin_airport_code": "BOG",
        "destination_airport_code": "MDE",
        "departure_date": date(2026, 11, 20),
        "origin_time": time(15, 20),
        "destination_time": time(16, 15),
        "duration_minutes": 55,
        "price_minor_units": 209900,
        "available_seats": 12,
        "status": "DELAYED",
    },
    {
        "id": "flight-410",
        "flight_number": "AA 410",
        "origin_airport_code": "BOG",
        "destination_airport_code": "CLO",
        "departure_date": date(2026, 11, 19),
        "origin_time": time(13, 0),
        "destination_time": time(14, 2),
        "duration_minutes": 62,
        "price_minor_units": 176000,
        "available_seats": 0,
        "status": "ON_TIME",
    },
)


async def main() -> None:
    now = datetime.now(UTC)
    async with SessionFactory() as session:
        for city_name, city_id in DEMO_CITIES.items():
            existing_city = await session.get(CityRecord, city_id)
            if existing_city is None:
                session.add(CityRecord(id=city_id, name=city_name, country_code="CO"))

        existing_airline = await session.get(AirlineRecord, DEMO_AIRLINE_ID)
        if existing_airline is None:
            session.add(
                AirlineRecord(id=DEMO_AIRLINE_ID, name="AeroAndes")
            )

        existing_currency = await session.get(CurrencyRecord, "COP")
        if existing_currency is None:
            session.add(
                CurrencyRecord(code="COP", name="Colombian peso", minor_unit=0)
            )

        await session.flush()

        for airport_code, city_name in DEMO_AIRPORTS.items():
            existing_airport = await session.get(AirportRecord, airport_code)
            if existing_airport is None:
                session.add(
                    AirportRecord(
                        iata_code=airport_code,
                        city_id=DEMO_CITIES[city_name],
                    )
                )

        await session.flush()
        for flight_data in DEMO_FLIGHTS:
            flight_id = flight_data["id"]
            existing_flight = await session.get(FlightRecord, flight_id)
            available_count = flight_data["available_seats"]
            if existing_flight is None:
                session.add(
                    FlightRecord(
                        id=flight_id,
                        airline_id=DEMO_AIRLINE_ID,
                        flight_number=flight_data["flight_number"],
                        origin_airport_code=flight_data["origin_airport_code"],
                        destination_airport_code=flight_data[
                            "destination_airport_code"
                        ],
                        departure_date=flight_data["departure_date"],
                        origin_time=flight_data["origin_time"],
                        destination_time=flight_data["destination_time"],
                        duration_minutes=flight_data["duration_minutes"],
                        price_minor_units=flight_data["price_minor_units"],
                        currency_code="COP",
                        status=flight_data["status"],
                    )
                )
                await session.flush()

            for seat_index, seat_number in enumerate(SEAT_NUMBERS):
                seat = await session.get(FlightSeatRecord, (flight_id, seat_number))
                if seat is None:
                    seat = FlightSeatRecord(
                        flight_id=flight_id,
                        seat_number=seat_number,
                        status="AVAILABLE",
                    )
                    session.add(seat)
                    await session.flush()

                # Reconcile only unclaimed fixture seats. Real reservations and
                # inventory operations carry their own reservation identity.
                if seat.held_for_reservation_id is not None and not (
                    seat.held_for_reservation_id.startswith("demo-")
                ):
                    continue

                seat.status = (
                    "AVAILABLE" if seat_index < available_count else "UNAVAILABLE"
                )
                seat.held_for_reservation_id = None
                seat.hold_expires_at = None
                override = DEMO_SEAT_OVERRIDES.get((flight_id, seat_number))
                if override is None:
                    continue
                seat.status, seat.held_for_reservation_id = override
                if seat.status == "HELD":
                    seat.hold_expires_at = now + timedelta(
                        minutes=DEMO_HOLD_TTL_MINUTES
                    )

        await session.commit()
    print(
        "Demo data ready: 4 flights; BOG–MDE has available seats and a held/"
        "booked example, flight-522 is delayed, and flight-410 is sold out."
    )


if __name__ == "__main__":
    asyncio.run(main())
