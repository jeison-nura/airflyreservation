"""Private WebSocket delivery for persisted reservation notifications."""

import asyncio
from typing import Any

from fastapi import WebSocket

from flight_booking.shared.observability import log_context, log_event
from flight_booking.shared.realtime import flight_seat_connections


class ReservationConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, reservation_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.register(reservation_id, websocket)

    def register(self, reservation_id: str, websocket: WebSocket) -> None:
        self._connections.setdefault(reservation_id, set()).add(websocket)

    def disconnect(self, reservation_id: str, websocket: WebSocket) -> None:
        connections = self._connections.get(reservation_id)
        if connections is None:
            return
        connections.discard(websocket)
        if not connections:
            self._connections.pop(reservation_id, None)

    async def publish(self, event: dict[str, object]) -> None:
        reservation_id = event.get("reservationId")
        if not isinstance(reservation_id, str):
            return
        message = {
            "type": "reservation.updated",
            "notificationId": event.get("notificationId"),
            "sequence": event.get("sequence"),
            "status": event.get("status"),
            "bookingCode": event.get("bookingCode"),
            "failureReason": event.get("failureReason"),
        }
        stale: list[WebSocket] = []
        for connection in tuple(self._connections.get(reservation_id, ())):
            try:
                await connection.send_json(message)
            except Exception:  # noqa: BLE001 - disconnected sockets are removed
                stale.append(connection)
        for connection in stale:
            self.disconnect(reservation_id, connection)


reservation_connections = ReservationConnectionManager()


async def _handle_stream_event(envelope: dict[str, Any]) -> None:
    if (
        envelope.get("source") == "inventory"
        and envelope.get("eventType")
        in ("SeatHeld", "SeatHoldReplaced", "SeatBooked", "SeatReleased", "SeatHoldExpired")
        and isinstance(envelope.get("payload"), dict)
    ):
        await flight_seat_connections.publish(envelope["payload"])
        module = "inventory"
    elif (
        envelope.get("source") == "reservations"
        and envelope.get("eventType") == "ReservationStatusChanged"
        and isinstance(envelope.get("payload"), dict)
    ):
        await reservation_connections.publish(envelope["payload"])
        module = "reservations"
    else:
        return
    log_event(
        module, "websocket_event_processed",
        correlation_id=envelope.get("correlationId"),
    )


async def run_stream_delivery() -> None:
    from flight_booking.modules.reservations.adapters.worker.stream_consumer import (
        RedisReservationEventConsumer,
    )

    consumer = RedisReservationEventConsumer(
        _handle_stream_event,
        group="reservations-websocket-v1",
        consumer="reservations-api",
    )
    try:
        while True:
            with log_context("redis_stream"):
                try:
                    await consumer.run_once()
                except Exception as exc:  # noqa: BLE001 - retry on transport failures
                    log_event(
                        "reservations", "stream_delivery_failed",
                        level="WARNING", error_type=type(exc).__name__,
                    )
                    await asyncio.sleep(1)
    finally:
        await consumer.close()
