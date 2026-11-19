"""Reusable Redis Streams consumer group for Reservations-owned event handlers."""

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis

from flight_booking.modules.reservations.adapters.persistence.inbox import (
    EventHandler,
    SqlAlchemyReservationInboxRepository,
)
from flight_booking.shared.messaging.redis_streams import (
    EVENT_STREAM,
    REDIS_URL,
)
from flight_booking.shared.observability import log_event

CONSUMER_GROUP = os.getenv("RESERVATIONS_EVENT_GROUP", "reservations-v1")
CONSUMER_NAME = os.getenv("RESERVATIONS_CONSUMER_NAME", "reservations-worker")
Handler = Callable[[dict[str, Any]], Awaitable[None]]


class InboxBackedHandler:
    """Wrap business event handling in the module's transactional inbox."""

    def __init__(
        self,
        repository: SqlAlchemyReservationInboxRepository,
        consumer: str,
        handler: EventHandler,
    ) -> None:
        self._repository = repository
        self._consumer = consumer
        self._handler = handler

    async def __call__(self, envelope: dict[str, Any]) -> None:
        await self._repository.process(
            envelope,
            consumer=self._consumer,
            handler=self._handler,
        )


class RedisReservationEventConsumer:
    def __init__(
        self,
        handler: Handler,
        *,
        redis: Redis | None = None,
        stream: str = EVENT_STREAM,
        group: str = CONSUMER_GROUP,
        consumer: str = CONSUMER_NAME,
    ) -> None:
        self._handler = handler
        self._redis = redis or Redis.from_url(REDIS_URL, decode_responses=True)
        self._stream = stream
        self._group = group
        self._consumer = consumer

    async def run_once(self, *, block_ms: int = 1000) -> int:
        try:
            await self._redis.xgroup_create(
                self._stream, self._group, id="$", mkstream=True
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        claimed = await self._redis.xautoclaim(
            self._stream,
            self._group,
            self._consumer,
            min_idle_time=30_000,
            start_id="0-0",
            count=25,
        )
        messages = claimed[1] if claimed and len(claimed) > 1 else []
        if not messages:
            batches = await self._redis.xreadgroup(
                self._group,
                self._consumer,
                {self._stream: ">"},
                count=25,
                block=block_ms,
            )
            messages = batches[0][1] if batches else []
        processed = 0
        for stream_id, fields in messages:
            correlation_id = None
            try:
                envelope = json.loads(fields["envelope"])
                if not isinstance(envelope, dict):
                    raise TypeError("Envelope must be an object")
                correlation_id = envelope.get("correlationId")
                await self._handler(envelope)
                await self._redis.xack(self._stream, self._group, stream_id)
                processed += 1
            except Exception as exc:  # noqa: BLE001 - leave failed stream entry pending
                log_event(
                    "reservations", "stream_handler_failed",
                    correlation_id=correlation_id, level="WARNING",
                    error_type=type(exc).__name__,
                )
                continue
        return processed

    async def close(self) -> None:
        await self._redis.aclose()


async def run_forever(handler: Handler) -> None:
    consumer = RedisReservationEventConsumer(handler)
    try:
        while True:
            await consumer.run_once()
    finally:
        await consumer.close()


if __name__ == "__main__":
    async def _unconfigured_handler(_: dict[str, Any]) -> None:
        raise RuntimeError("Reservations event handler is not configured")

    asyncio.run(run_forever(_unconfigured_handler))
