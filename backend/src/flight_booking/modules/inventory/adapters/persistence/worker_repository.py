"""Inventory-only PostgreSQL polling and outbox delivery leases."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flight_booking.modules.inventory.adapters.persistence.models import (
    FlightSeatRecord,
    OutboxEventRecord,
)
from flight_booking.modules.inventory.application.ports import ExpiredSeatRepository


class SqlAlchemyExpiredSeatRepository(ExpiredSeatRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find_due(self, now: datetime, limit: int) -> list[tuple[str, str]]:
        async with self._session_factory() as session:
            rows = await session.execute(
                select(FlightSeatRecord.flight_id, FlightSeatRecord.seat_number)
                .where(
                    FlightSeatRecord.status == "HELD",
                    FlightSeatRecord.hold_expires_at <= now,
                )
                .order_by(
                    FlightSeatRecord.hold_expires_at,
                    FlightSeatRecord.flight_id,
                    FlightSeatRecord.seat_number,
                )
                .limit(limit)
            )
            return [(flight_id, seat_number) for flight_id, seat_number in rows]


@dataclass(frozen=True)
class OutboxMessage:
    id: str
    source: str
    event_type: str
    schema_version: int
    flight_id: str
    seat_number: str
    payload: dict[str, Any]
    occurred_at: datetime
    correlation_id: str
    causation_id: str
    claim_token: str

    @property
    def event_id(self) -> str:
        """Match the shared Redis event transport contract."""
        return self.id


class SqlAlchemyOutboxRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim(
        self, consumer: str, now: datetime, *, limit: int, lease_seconds: int
    ) -> list[OutboxMessage]:
        if not consumer or len(consumer) > 64 or limit < 1 or lease_seconds < 1:
            raise ValueError("Invalid outbox lease request")
        async with self._session_factory() as session, session.begin():
            rows = (
                await session.scalars(
                    select(OutboxEventRecord)
                    .where(
                        OutboxEventRecord.delivered_at.is_(None),
                        or_(
                            OutboxEventRecord.claim_until.is_(None),
                            OutboxEventRecord.claim_until <= now,
                        ),
                    )
                    .order_by(OutboxEventRecord.occurred_at, OutboxEventRecord.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            tokens: dict[str, str] = {}
            for row in rows:
                row.claimed_by = consumer
                tokens[row.id] = uuid4().hex
                row.claim_token = tokens[row.id]
                row.claim_until = now + timedelta(seconds=lease_seconds)
                row.attempts += 1
            return [
                OutboxMessage(
                    id=row.id,
                    source=row.source,
                    event_type=row.event_type,
                    schema_version=row.schema_version,
                    flight_id=row.flight_id,
                    seat_number=row.seat_number,
                    payload=row.payload,
                    occurred_at=row.occurred_at,
                    correlation_id=row.correlation_id,
                    causation_id=row.causation_id,
                    claim_token=tokens[row.id],
                )
                for row in rows
            ]

    async def ack(
        self, event_id: str, consumer: str, now: datetime, *, claim_token: str
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                update(OutboxEventRecord)
                .where(
                    OutboxEventRecord.id == event_id,
                    OutboxEventRecord.claimed_by == consumer,
                    OutboxEventRecord.claim_token == claim_token,
                    OutboxEventRecord.claim_until > now,
                    OutboxEventRecord.delivered_at.is_(None),
                )
                .values(
                    delivered_at=now,
                    claimed_by=None,
                    claim_token=None,
                    claim_until=None,
                )
            )
            return cast(CursorResult[Any], result).rowcount == 1
