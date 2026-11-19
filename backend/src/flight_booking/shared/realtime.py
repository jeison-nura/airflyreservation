"""In-process WebSocket fan-out for public Inventory seat state."""

import os

from fastapi import WebSocket

WS_ALLOWED_ORIGINS = frozenset(
    origin.strip()
    for origin in os.getenv(
        "RESERVATION_WS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
)


class FlightSeatConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, flight_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(flight_id, set()).add(websocket)

    def disconnect(self, flight_id: str, websocket: WebSocket) -> None:
        connections = self._connections.get(flight_id)
        if connections is None:
            return
        connections.discard(websocket)
        if not connections:
            self._connections.pop(flight_id, None)

    async def publish(self, payload: dict[str, object]) -> None:
        flight_id = payload.get("flightId")
        seat_number = payload.get("seatNumber")
        status = payload.get("status")
        if not all(isinstance(value, str) for value in (flight_id, seat_number, status)):
            return
        message = {
            "type": "seat.updated",
            "flightId": flight_id,
            "seatNumber": seat_number,
            "status": status,
        }
        stale: list[WebSocket] = []
        for websocket in tuple(self._connections.get(flight_id, ())):
            try:
                await websocket.send_json(message)
            except Exception:  # noqa: BLE001 - disconnected sockets are removed
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(flight_id, websocket)


flight_seat_connections = FlightSeatConnectionManager()
