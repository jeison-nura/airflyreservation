from datetime import UTC, datetime

from flight_booking.modules.inventory.adapters.persistence.worker_repository import (
    OutboxMessage,
)
from flight_booking.shared.messaging.redis_streams import event_envelope


def test_inventory_outbox_message_matches_shared_stream_envelope():
    message = OutboxMessage(
        id="event-123",
        source="inventory",
        event_type="SeatHeld",
        schema_version=1,
        flight_id="flight-204",
        seat_number="2A",
        payload={
            "flightId": "flight-204",
            "seatNumber": "2A",
            "status": "HELD",
        },
        occurred_at=datetime(2026, 11, 19, tzinfo=UTC),
        correlation_id="correlation-123",
        causation_id="causation-123",
        claim_token="claim-123",
    )

    envelope = event_envelope(message)

    assert envelope["eventId"] == "event-123"
    assert envelope["eventType"] == "SeatHeld"
    assert envelope["source"] == "inventory"
