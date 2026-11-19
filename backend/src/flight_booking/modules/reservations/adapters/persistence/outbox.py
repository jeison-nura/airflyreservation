"""PostgreSQL delivery leases for the Reservations transactional outbox."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flight_booking.modules.reservations.adapters.persistence.models import (
    ReservationOutboxRecord,
)


@dataclass(frozen=True)
class ReservationOutboxMessage:
    event_id: str
    source: str
    event_type: str
    schema_version: int
    payload: dict[str, Any]
    occurred_at: datetime
    correlation_id: str
    causation_id: str
    claim_token: str


class SqlAlchemyReservationOutboxRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim(
        self, consumer: str, now: datetime, *, limit: int, lease_seconds: int
    ) -> list[ReservationOutboxMessage]:
        if not consumer or len(consumer) > 64 or limit < 1 or lease_seconds < 1:
            raise ValueError("Invalid outbox lease request")
        async with self._session_factory() as session, session.begin():
            rows = (
                await session.scalars(
                    select(ReservationOutboxRecord)
                    .where(
                        ReservationOutboxRecord.delivered_at.is_(None),
                        or_(
                            ReservationOutboxRecord.claim_until.is_(None),
                            ReservationOutboxRecord.claim_until <= now,
                        ),
                    )
                    .order_by(
                        ReservationOutboxRecord.occurred_at,
                        ReservationOutboxRecord.event_id,
                    )
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            result = []
            for row in rows:
                token = uuid4().hex
                row.claimed_by = consumer
                row.claim_token = token
                row.claim_until = now + timedelta(seconds=lease_seconds)
                row.attempts += 1
                result.append(
                    ReservationOutboxMessage(
                        event_id=row.event_id,
                        source="reservations",
                        event_type=row.event_type,
                        schema_version=row.schema_version,
                        payload=row.payload,
                        occurred_at=row.occurred_at,
                        correlation_id=row.correlation_id,
                        causation_id=row.causation_id,
                        claim_token=token,
                    )
                )
            return result

    async def ack(
        self,
        event_id: str,
        consumer: str,
        now: datetime,
        *,
        claim_token: str,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                update(ReservationOutboxRecord)
                .where(
                    ReservationOutboxRecord.event_id == event_id,
                    ReservationOutboxRecord.claimed_by == consumer,
                    ReservationOutboxRecord.claim_token == claim_token,
                    ReservationOutboxRecord.claim_until > now,
                    ReservationOutboxRecord.delivered_at.is_(None),
                )
                .values(
                    delivered_at=now,
                    claimed_by=None,
                    claim_token=None,
                    claim_until=None,
                )
            )
            return cast(CursorResult[Any], result).rowcount == 1
