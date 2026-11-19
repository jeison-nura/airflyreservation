import asyncio
from datetime import date, time

import pytest
from httpx import ASGITransport, AsyncClient

from flight_booking.main import app
from flight_booking.modules.inventory.adapters.http.router import get_search_flights
from flight_booking.modules.inventory.application.ports import FlightSearchResult
from flight_booking.modules.inventory.domain.models import Airport, Flight, FlightStatus


class FixedSearchFlights:
    async def execute(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: date,
        page: int,
        page_size: int,
    ):
        assert (origin, destination, departure_date, page, page_size) == (
            "BOG",
            "MDE",
            date(2026, 11, 19),
            1,
            20,
        )
        return FlightSearchResult(
            flights=[
                Flight(
                    id="flight-204",
                    airline="AeroAndes",
                    flight_number="AA 204",
                    origin=Airport("BOG", "Bogotá", time(7, 10)),
                    destination=Airport("MDE", "Medellín", time(8, 5)),
                    departure_date=date(2026, 11, 19),
                    duration="55 min",
                    price=189900,
                    currency="COP",
                    available_seats=18,
                    status=FlightStatus.ON_TIME,
                )
            ],
            total_items=1,
        )


@pytest.fixture
def search():
    async def override_search_flights():
        return FixedSearchFlights()

    app.dependency_overrides[get_search_flights] = override_search_flights

    def request(params):
        async def send():
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                return await client.get("/api/v1/inventory/flights", params=params)

        return asyncio.run(send())

    yield request
    app.dependency_overrides.clear()


def test_search_returns_the_frontend_flight_contract(search):
    response = search(
        {"origin": "BOG", "destination": "MDE", "departureDate": "2026-11-19"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "id": "flight-204",
                "airline": "AeroAndes",
                "flightNumber": "AA 204",
                "origin": {"code": "BOG", "city": "Bogotá", "time": "07:10"},
                "destination": {"code": "MDE", "city": "Medellín", "time": "08:05"},
                "departureDate": "2026-11-19",
                "duration": "55 min",
                "price": 189900,
                "currency": "COP",
                "availableSeats": 18,
                "status": "ON_TIME",
            }
        ],
        "pagination": {"page": 1, "pageSize": 20, "totalItems": 1, "totalPages": 1},
    }


@pytest.mark.parametrize(
    "params",
    [
        {"origin": "bog", "destination": "BOG", "departureDate": "2026-11-19"},
        {"origin": "BO", "destination": "MDE", "departureDate": "2026-11-19"},
        {"origin": "BOG", "destination": "MDE", "departureDate": "not-a-date"},
        {"origin": "BOG", "destination": "MDE", "departureDate": "2026-11-19", "page": 0},
        {"origin": "BOG", "destination": "MDE", "departureDate": "2026-11-19", "pageSize": 101},
        {"origin": "BOG", "destination": "MDE", "departureDate": "2026-11-19", "pageSize": 0},
        {"origin": "BOG", "destination": "MDE", "departureDate": "2026-11-19", "page": "x"},
        {"origin": "BOG", "destination": "MDE", "departureDate": "2026-11-19", "pageSize": "x"},
    ],
)
def test_search_rejects_invalid_criteria(search, params):
    response = search(params)

    assert response.status_code == 422


def test_search_passes_pagination_to_use_case_and_returns_empty_page_metadata(search):
    class EmptySecondPage:
        async def execute(
            self,
            *,
            origin: str,
            destination: str,
            departure_date: date,
            page: int,
            page_size: int,
        ):
            assert (page, page_size) == (2, 1)
            return FlightSearchResult(flights=[], total_items=1)

    app.dependency_overrides[get_search_flights] = lambda: EmptySecondPage()
    response = search(
        {
            "origin": "BOG",
            "destination": "MDE",
            "departureDate": "2026-11-19",
            "page": 2,
            "pageSize": 1,
        }
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": [],
        "pagination": {"page": 2, "pageSize": 1, "totalItems": 1, "totalPages": 1},
    }


def test_search_without_matches_has_zero_total_pages(search):
    class NoMatches:
        async def execute(self, **criteria):
            assert (criteria["page"], criteria["page_size"]) == (1, 20)
            return FlightSearchResult(flights=[], total_items=0)

    app.dependency_overrides[get_search_flights] = lambda: NoMatches()
    response = search(
        {"origin": "BOG", "destination": "MDE", "departureDate": "2026-11-19"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": [],
        "pagination": {"page": 1, "pageSize": 20, "totalItems": 0, "totalPages": 0},
    }
