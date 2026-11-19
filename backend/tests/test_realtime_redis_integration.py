"""Exercise Redis delivery through the public ASGI WebSocket on a local test stack."""

import os
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.websockets import WebSocketDisconnect

from flight_booking.modules.inventory.adapters.http import router as inventory_http
from flight_booking.modules.inventory.adapters.persistence.session import DATABASE_URL
from flight_booking.modules.inventory.adapters.persistence.worker_repository import (
    OutboxMessage,
)
from flight_booking.modules.reservations.adapters.http.realtime import (
    _handle_stream_event,
)
from flight_booking.modules.reservations.adapters.worker.stream_consumer import (
    RedisReservationEventConsumer,
)
from flight_booking.shared.messaging import redis_streams

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_REALTIME_REDIS_TESTS") != "1",
    reason="Requires local Redis and migrated PostgreSQL with demo flights",
)


def test_two_inventory_websockets_receive_hold_release_and_booking(monkeypatch):
    stream = f"flight_booking:test:{uuid4().hex}"
    monkeypatch.setattr(redis_streams, "EVENT_STREAM", stream)
    # TestClient runs on a separate event loop from the repository tests.
    engine = create_async_engine(DATABASE_URL, hide_parameters=True)
    monkeypatch.setattr(inventory_http, "SessionFactory", async_sessionmaker(engine))
    app = FastAPI()
    app.include_router(inventory_http.router, prefix="/api/v1/inventory")
    origin = {"origin": "http://localhost:3000"}
    path = "/api/v1/inventory/flights/flight-204/events/ws"
    sent_frame_counts = []

    async def observe_frames(scope, receive, send):
        if scope["type"] != "websocket":
            await app(scope, receive, send)
            return
        sent_frame_counts.append(0)
        index = len(sent_frame_counts) - 1

        async def record(message):
            if message["type"] == "websocket.send":
                sent_frame_counts[index] += 1
            await send(message)

        await app(scope, receive, record)

    async def publish_and_relay():
        redis = Redis.from_url(redis_streams.REDIS_URL, decode_responses=True, socket_timeout=3)
        consumer = RedisReservationEventConsumer(
            _handle_stream_event, redis=redis, stream=stream, group="test-group"
        )
        base = OutboxMessage(
            id=uuid4().hex,
            source="inventory",
            event_type="SeatHeld",
            schema_version=1,
            flight_id="flight-204",
            seat_number="1A",
            payload={
                "flightId": "flight-204",
                "seatNumber": "1A",
                "status": "HELD",
                "reservationId": "not-for-public-broadcast",
            },
            occurred_at=datetime.now(UTC),
            correlation_id=uuid4().hex,
            causation_id=uuid4().hex,
            claim_token=uuid4().hex,
        )
        try:
            await redis.xgroup_create(stream, "test-group", id="0", mkstream=True)
            for event_type, status in (
                ("SeatHeld", "HELD"),
                ("SeatHoldExpired", "AVAILABLE"),
                ("SeatBooked", "BOOKED"),
            ):
                await redis_streams.publish_event(
                    redis,
                    replace(
                        base,
                        id=uuid4().hex,
                        event_type=event_type,
                        payload={**base.payload, "status": status},
                    ),
                )
            assert await consumer.run_once(block_ms=100) == 3
        finally:
            await redis.delete(stream)
            await consumer.close()

    with TestClient(observe_frames) as client:
        try:
            with pytest.raises(WebSocketDisconnect) as denied, client.websocket_connect(path):
                pytest.fail("Connection without an allowed Origin was accepted")
            assert denied.value.code == 1008
            with (
                client.websocket_connect(path, headers=origin) as first,
                client.websocket_connect(path, headers=origin) as second,
            ):
                assert client.portal is not None
                client.portal.call(publish_and_relay)
                # Assert the frames are queued before using the blocking test receive.
                assert sent_frame_counts == [0, 3, 3]
                for socket in (first, second):
                    for status in ("HELD", "AVAILABLE", "BOOKED"):
                        assert socket.receive_json() == {
                            "type": "seat.updated",
                            "flightId": "flight-204",
                            "seatNumber": "1A",
                            "status": status,
                        }
        finally:
            assert client.portal is not None
            client.portal.call(engine.dispose)
