import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from flight_booking.main import app


def test_health_endpoint_reports_process_status(capsys) -> None:
    async def send_request():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get("/health?private=never-log-this")

    response = asyncio.run(send_request())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    line = capsys.readouterr().out
    record = json.loads(line)
    assert record["event"] == "http_request"
    assert record["entry_point"] == "http"
    assert record["route"] == "/health"
    assert record["status_code"] == 200
    assert record["request_id"] == response.headers["X-Request-ID"]
    assert "never-log-this" not in line


def test_openapi_uses_versioned_api_prefix() -> None:
    schema = app.openapi()

    assert "/health" in schema["paths"]
    assert all(path.startswith("/api/v1/") or path == "/health" for path in schema["paths"])


def test_rejected_websocket_logs_close_code_and_route_without_client_values(capsys) -> None:
    client = TestClient(app)
    with (
        pytest.raises(WebSocketDisconnect) as rejected,
        client.websocket_connect(
            "/api/v1/inventory/flights/client-flight-id/events/ws?secret=unlogged",
            headers={"Origin": "https://unallowed.example.test"},
        ),
    ):
        pytest.fail("WebSocket should not accept this origin")
    assert rejected.value.code == 1008

    line = capsys.readouterr().out
    record = json.loads(line)
    assert record["event"] == "websocket_session"
    assert record["entry_point"] == "websocket"
    assert record["route"] == "/api/v1/inventory/flights/{flight_id}/events/ws"
    assert record["close_code"] == 1008
    assert "client-flight-id" not in line
    assert "unlogged" not in line
