import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from flight_booking.main import app
from flight_booking.modules.inventory.adapters.http.router import get_flight_seats
from flight_booking.modules.inventory.application.get_flight_seats import GetFlightSeats
from flight_booking.modules.inventory.domain.models import FlightSeat, SeatStatus


class FixedSeatRepository:
    async def get_by_flight(self, flight_id: str):
        if flight_id != "flight-204":
            return None
        return [
            FlightSeat("flight-204", "1A", SeatStatus.AVAILABLE),
            FlightSeat("flight-204", "1B", SeatStatus.HELD),
            FlightSeat("flight-204", "1C", SeatStatus.BOOKED),
        ]


@pytest.fixture
def seat_request():
    app.dependency_overrides[get_flight_seats] = lambda: GetFlightSeats(FixedSeatRepository())

    def send(flight_id: str):
        async def fetch():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                return await client.get(f"/api/v1/inventory/flights/{flight_id}/seats")

        return asyncio.run(fetch())

    yield send
    app.dependency_overrides.clear()


def test_seat_map_returns_each_seat_status_without_reservation_details(seat_request):
    response = seat_request("flight-204")

    assert response.status_code == 200
    assert response.json() == {
        "flightId": "flight-204",
        "seats": [
            {"seatNumber": "1A", "status": "AVAILABLE"},
            {"seatNumber": "1B", "status": "HELD"},
            {"seatNumber": "1C", "status": "BOOKED"},
        ],
    }


def test_unknown_flight_returns_not_found(seat_request):
    assert seat_request("flight-missing").status_code == 404


def test_oversized_flight_id_is_rejected(seat_request):
    assert seat_request("a" * 65).status_code == 422
