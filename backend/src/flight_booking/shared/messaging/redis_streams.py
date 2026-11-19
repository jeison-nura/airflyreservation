"""Redis Streams event transport; PostgreSQL outboxes remain the source of truth."""

import json
import os
from datetime import UTC, datetime
from typing import Any, Protocol

from redis.asyncio import Redis

from flight_booking.shared.observability import log_event

EVENT_STREAM = os.getenv("EVENT_STREAM_NAME", "flight_booking:events:v1")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


class OutboxMessage(Protocol):
    event_id: str
    source: str
    event_type: str
    schema_version: int
    payload: dict[str, Any]
    occurred_at: datetime
    correlation_id: str
    causation_id: str


def event_envelope(message: OutboxMessage) -> dict[str, Any]:
    return {
        "eventId": message.event_id,
        "eventType": message.event_type,
        "schemaVersion": message.schema_version,
        "source": message.source,
        "occurredAt": message.occurred_at.isoformat(),
        "correlationId": message.correlation_id,
        "causationId": message.causation_id,
        "payload": message.payload,
    }


async def publish_event(redis: Redis, message: OutboxMessage) -> str:
    envelope = event_envelope(message)
    stream_id = await redis.xadd(
        EVENT_STREAM,
        {
            "event_id": message.event_id,
            "envelope": json.dumps(
                envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ),
        },
    )
    return stream_id.decode() if isinstance(stream_id, bytes) else str(stream_id)


async def dispatch_outbox_batch(
    repository: Any,
    *,
    consumer: str,
    batch_size: int = 100,
    lease_seconds: int = 30,
    redis_factory: Any = Redis.from_url,
) -> int:
    """Publish then ack; a crash between these steps safely causes a duplicate."""
    redis = redis_factory(REDIS_URL, decode_responses=True)
    delivered = 0
    try:
        messages = await repository.claim(
            consumer,
            datetime.now(UTC),
            limit=batch_size,
            lease_seconds=lease_seconds,
        )
        for message in messages:
            await publish_event(redis, message)
            acknowledged = await repository.ack(
                message.event_id,
                consumer,
                datetime.now(UTC),
                claim_token=message.claim_token,
            )
            delivered += int(acknowledged)
            log_event(
                message.source, "outbox_published",
                correlation_id=message.correlation_id,
                operation=message.event_type, acknowledged=acknowledged,
                level="INFO" if acknowledged else "WARNING",
            )
    finally:
        await redis.aclose()
    return delivered
