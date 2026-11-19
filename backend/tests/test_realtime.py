import asyncio
import json
from typing import cast

from fastapi import WebSocket

from flight_booking.modules.reservations.adapters.http import realtime
from flight_booking.shared.observability import log_context
from flight_booking.shared.realtime import FlightSeatConnectionManager


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def accept(self) -> None:
        return None

    async def send_json(self, message: dict[str, object]) -> None:
        self.messages.append(message)


def test_inventory_seat_broadcast_is_scoped_and_redacts_reservation_identity():
    async def exercise():
        manager = FlightSeatConnectionManager()
        flight_socket = FakeWebSocket()
        other_socket = FakeWebSocket()
        await manager.connect("flight-1", flight_socket)  # type: ignore[arg-type]
        await manager.connect("flight-2", other_socket)  # type: ignore[arg-type]

        await manager.publish(
            {
                "flightId": "flight-1",
                "seatNumber": "4A",
                "status": "HELD",
                "reservationId": "private-reservation-id",
            }
        )

        assert flight_socket.messages == [
            {
                "type": "seat.updated",
                "flightId": "flight-1",
                "seatNumber": "4A",
                "status": "HELD",
            }
        ]
        assert other_socket.messages == []
        manager.disconnect("flight-1", flight_socket)  # type: ignore[arg-type]
        manager.disconnect("flight-2", other_socket)  # type: ignore[arg-type]

    asyncio.run(exercise())


def test_private_relay_only_publishes_status_for_the_subscribed_reservation(monkeypatch, capsys):
    async def exercise():
        manager = realtime.ReservationConnectionManager()
        monkeypatch.setattr(realtime, "reservation_connections", manager)
        owner = FakeWebSocket()
        other = FakeWebSocket()
        await manager.connect("reservation-1", cast(WebSocket, owner))
        await manager.connect("reservation-2", cast(WebSocket, other))

        payload = {
            "reservationId": "reservation-1",
            "notificationId": "event-1",
            "sequence": 2,
            "status": "CONFIRMED",
            "bookingCode": "AF-DEMO",
            "failureReason": None,
            "privateField": "not-for-broadcast",
        }
        await realtime._handle_stream_event(
            {"source": "reservations", "eventType": "ReservationSagaProgressed", "payload": payload}
        )
        assert owner.messages == []
        with log_context("redis_stream"):
            await realtime._handle_stream_event({
                "source": "reservations", "eventType": "ReservationStatusChanged",
                "payload": payload, "correlationId": "b" * 32,
            })
        assert owner.messages == [{
            "type": "reservation.updated",
            "notificationId": "event-1",
            "sequence": 2,
            "status": "CONFIRMED",
            "bookingCode": "AF-DEMO",
            "failureReason": None,
        }]
        assert other.messages == []

        manager.disconnect("reservation-1", cast(WebSocket, owner))
        await manager.publish(payload)
        assert len(owner.messages) == 1

    asyncio.run(exercise())
    line = capsys.readouterr().out
    record = json.loads(line)
    assert record["event"] == "websocket_event_processed"
    assert record["entry_point"] == "redis_stream"
    assert record["correlation_id"] == "b" * 32
    assert "AF-DEMO" not in line
    assert "not-for-broadcast" not in line
