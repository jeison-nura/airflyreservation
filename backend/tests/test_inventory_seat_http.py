import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from flight_booking.main import app
from flight_booking.modules.inventory.adapters.http.seat_commands import (
    get_seat_clock,
    get_seat_mutations,
)
from flight_booking.modules.inventory.domain.models import FlightStatus, SeatStatus
from flight_booking.modules.inventory.domain.seat_allocation import SeatAllocation

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)


class FixedClock:
    def now(self):
        return NOW


class MemoryRepository:
    def __init__(self):
        self.seats = {
            ("flight-204", "1A"): SeatAllocation(
                "flight-204", "1A", SeatStatus.AVAILABLE, FlightStatus.ON_TIME
            )
        }

    async def mutate(self, flight_id, seat_number, transition, *, context=None):
        seat = self.seats.get((flight_id, seat_number))
        if seat is None:
            return None
        changed = transition(seat)
        self.seats[(flight_id, seat_number)] = changed
        return changed


@pytest.fixture
def send(monkeypatch):
    repository = MemoryRepository()
    monkeypatch.setenv("INVENTORY_INTERNAL_TOKEN", "local-test-secret-long-enough")
    app.dependency_overrides[get_seat_mutations] = lambda: repository
    app.dependency_overrides[get_seat_clock] = lambda: FixedClock()

    def request(
        operation, body=None, *, token="local-test-secret-long-enough",
        flight_id="flight-204", idempotency_key="test-intent-123456",
    ):
        async def dispatch():
            headers = {}
            if idempotency_key is not None:
                headers["Idempotency-Key"] = idempotency_key
            if token is not None:
                headers["X-Inventory-Service-Token"] = token
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                return await client.post(
                    f"/api/v1/inventory/flights/{flight_id}/seats/1A/{operation}",
                    json=body,
                    headers=headers,
                )

        return asyncio.run(dispatch())

    yield request
    app.dependency_overrides.clear()


def test_commands_hold_confirm_release_and_expire(send):
    body = {"reservationId": "reservation-1", "expiresAt": (NOW + timedelta(minutes=10)).isoformat()}
    held = send("hold", body)
    assert held.status_code == 200
    assert held.json() == {"flightId": "flight-204", "seatNumber": "1A", "status": "HELD"}
    assert send("confirm", {"reservationId": "reservation-1"}).json()["status"] == "BOOKED"
    assert send("release", {"reservationId": "reservation-1"}).json()["status"] == "AVAILABLE"
    assert send("hold", body).status_code == 200
    # Not yet expired, so this is a no-op.
    assert send("expire").json()["status"] == "HELD"


def test_commands_refuse_unauthorized_and_disabled_requests(send, monkeypatch):
    assert send("hold", token=None).status_code == 401
    assert send("hold", token="wrong").status_code == 401
    monkeypatch.delenv("INVENTORY_INTERNAL_TOKEN")
    assert send("hold").status_code == 503


def test_commands_require_valid_idempotency_key(send):
    assert send("expire", idempotency_key=None).status_code == 422
    assert send("expire", idempotency_key="short").status_code == 422
    assert send("expire", idempotency_key="a" * 129).status_code == 422
    assert send("expire", idempotency_key="invalid key").status_code == 422


def test_commands_validate_input_and_translate_domain_errors(send):
    assert send("hold", {"reservationId": "r", "expiresAt": "2026-11-18T12:10:00"}).status_code == 422
    assert send("hold", {"reservationId": "r", "expiresAt": NOW.isoformat()}).status_code == 422
    assert send("hold", {"reservationId": "", "expiresAt": NOW.isoformat()}).status_code == 422
    assert send("hold", {"reservationId": "r", "expiresAt": (NOW + timedelta(minutes=1)).isoformat()}).status_code == 200
    assert send("hold", {"reservationId": "other", "expiresAt": (NOW + timedelta(minutes=1)).isoformat()}).status_code == 409
    assert send("confirm", {"reservationId": "other"}).status_code == 409
    assert send("release", {"reservationId": "other"}).status_code == 409
    assert send("confirm", {"reservationId": "r"}, flight_id="unknown").status_code == 404


def test_expired_hold_cannot_be_confirmed_and_can_be_released(send):
    expiration = (NOW + timedelta(minutes=1)).isoformat()
    assert send("hold", {"reservationId": "r", "expiresAt": expiration}).status_code == 200

    class LaterClock:
        def now(self):
            return NOW + timedelta(minutes=1)

    app.dependency_overrides[get_seat_clock] = lambda: LaterClock()
    assert send("confirm", {"reservationId": "r"}).status_code == 409
    assert send("expire").json()["status"] == "AVAILABLE"
    assert send("confirm", {"reservationId": "r"}).status_code == 409
