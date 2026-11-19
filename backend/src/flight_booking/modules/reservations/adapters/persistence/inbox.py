"""Atomic inbox/deduplication and dead-letter recording for Reservations."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flight_booking.modules.reservations.adapters.persistence.models import (
    ReservationDeadLetterRecord,
    ReservationInboxRecord,
)

EventHandler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]


class PermanentEventError(Exception):
    """The event cannot be processed and must be dead-lettered."""

    def __init__(self, code: str) -> None:
        if not code or len(code) > 64:
            raise ValueError("Invalid dead-letter failure code")
        self.code = code
        super().__init__(code)


def _redacted_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Keep correlation/debug metadata and strip sensitive payload values."""
    payload = envelope.get("payload")
    safe_payload: dict[str, Any] = {}
    if isinstance(payload, dict):
        for key in ("reservationId", "status", "sequence", "eventType"):
            if key in payload:
                safe_payload[key] = payload[key]
    return {
        key: envelope[key]
        for key in (
            "eventId",
            "eventType",
            "schemaVersion",
            "source",
            "occurredAt",
            "correlationId",
            "causationId",
        )
        if key in envelope
    } | {"payload": safe_payload}


class SqlAlchemyReservationInboxRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def process(
        self,
        envelope: dict[str, Any],
        *,
        consumer: str,
        handler: EventHandler,
    ) -> str:
        event_id = envelope.get("eventId")
        correlation_id = envelope.get("correlationId")
        if not isinstance(event_id, str) or not isinstance(correlation_id, str):
            raise PermanentEventError("INVALID_EVENT_ENVELOPE")
        if len(consumer) > 64 or not consumer:
            raise ValueError("Invalid consumer name")
        try:
            async with self._session_factory() as session, session.begin():
                existing = await session.get(
                    ReservationInboxRecord, (consumer, event_id)
                )
                if existing and existing.status in ("PROCESSED", "DEAD_LETTERED"):
                    return existing.status
                record = existing or ReservationInboxRecord(
                    consumer=consumer,
                    event_id=event_id,
                    status="PROCESSING",
                    correlation_id=correlation_id,
                )
                if existing is None:
                    session.add(record)
                    await session.flush()
                try:
                    await handler(session, envelope)
                except PermanentEventError as exc:
                    session.add(
                        ReservationDeadLetterRecord(
                            id=uuid4().hex,
                            consumer=consumer,
                            event_id=event_id,
                            payload=_redacted_envelope(envelope),
                            failure_code=exc.code,
                            attempts=1,
                            occurred_at=datetime.now(UTC),
                        )
                    )
                    record.status = "DEAD_LETTERED"
                    record.processed_at = datetime.now(UTC)
                    return record.status
                record.status = "PROCESSED"
                record.processed_at = datetime.now(UTC)
                return record.status
        except IntegrityError:
            # Another delivery committed this event concurrently.
            async with self._session_factory() as session:
                existing = await session.scalar(
                    select(ReservationInboxRecord.status).where(
                        ReservationInboxRecord.consumer == consumer,
                        ReservationInboxRecord.event_id == event_id,
                    )
                )
            if existing in ("PROCESSED", "DEAD_LETTERED"):
                return existing
            raise
