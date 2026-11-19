import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_booking.modules.reservations.adapters.persistence.inbox import (
    PermanentEventError,
    SqlAlchemyReservationInboxRepository,
)
from flight_booking.modules.reservations.adapters.persistence.models import (
    Base,
    ReservationDeadLetterRecord,
    ReservationOutboxRecord,
)
from flight_booking.modules.reservations.adapters.persistence.outbox import (
    SqlAlchemyReservationOutboxRepository,
)
from flight_booking.modules.reservations.adapters.persistence.repository import (
    SqlAlchemyReservationRepository,
)
from flight_booking.modules.reservations.domain.models import (
    Reservation,
    ReservationAggregate,
    ReservationSaga,
)
from flight_booking.shared.messaging.redis_streams import (
    dispatch_outbox_batch,
    event_envelope,
)

NOW = datetime(2026, 11, 19, 12, tzinfo=UTC)


def database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def attach_schema(connection, _record):
        connection.execute("ATTACH DATABASE ':memory:' AS reservations")

    return engine


def test_reservation_outbox_claim_publish_ack_and_inbox_deduplicates():
    async def exercise():
        engine = database()
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            repository = SqlAlchemyReservationRepository(sessions)
            reservation = Reservation.start(
                "reservation-1",
                "flight-204",
                "4A",
                NOW,
                NOW + timedelta(minutes=10),
            )
            await repository.create_booking(
                ReservationAggregate(
                    reservation, ReservationSaga.start("reservation-1", "corr-1")
                ),
                full_name="Ada Lovelace",
                email="ada@example.test",
                access_credential_hash="a" * 64,
                idempotency_key="create-request-1",
                request_hash="b" * 64,
            )

            outbox = SqlAlchemyReservationOutboxRepository(sessions)
            messages = await outbox.claim(
                "test-publisher", NOW, limit=10, lease_seconds=30
            )
            assert len(messages) == 1
            envelope = event_envelope(messages[0])
            assert envelope["source"] == "reservations"
            assert envelope["eventType"] == "ReservationCreated"
            assert "email" not in str(envelope)
            assert not await outbox.ack(
                messages[0].event_id,
                "test-publisher",
                NOW,
                claim_token="stale-token",
            )
            assert await outbox.ack(
                messages[0].event_id,
                "test-publisher",
                NOW,
                claim_token=messages[0].claim_token,
            )

            class FakeRedis:
                def __init__(self):
                    self.entries = []
                    self.closed = False

                async def xadd(self, stream, fields):
                    self.entries.append((stream, fields))
                    return "1-0"

                async def aclose(self):
                    self.closed = True

            redis = FakeRedis()

            class FakeOutbox:
                async def claim(self, *_args, **_kwargs):
                    return messages

                async def ack(self, *_args, **_kwargs):
                    return True

            delivered = await dispatch_outbox_batch(
                FakeOutbox(),
                consumer="test-publisher",
                redis_factory=lambda *_args, **_kwargs: redis,
            )
            assert delivered == 1
            assert redis.closed
            assert redis.entries[0][1]["event_id"] == messages[0].event_id

            inbox = SqlAlchemyReservationInboxRepository(sessions)
            handled = 0

            async def handler(_session, _envelope):
                nonlocal handled
                handled += 1

            event = {
                "eventId": "payment-event-1",
                "eventType": "PaymentAuthorized",
                "schemaVersion": 1,
                "source": "payments",
                "occurredAt": NOW.isoformat(),
                "correlationId": "corr-1",
                "causationId": "cause-1",
                "payload": {"reservationId": "reservation-1"},
            }
            assert (
                await inbox.process(event, consumer="reservations", handler=handler)
                == "PROCESSED"
            )
            assert (
                await inbox.process(event, consumer="reservations", handler=handler)
                == "PROCESSED"
            )
            assert handled == 1

            async def poison_handler(_session, _envelope):
                raise PermanentEventError("UNSUPPORTED_EVENT")

            poison = {**event, "eventId": "bad-event-1", "payload": {"email": "x@y"}}
            assert (
                await inbox.process(
                    poison, consumer="reservations", handler=poison_handler
                )
                == "DEAD_LETTERED"
            )
            async with sessions() as session:
                letter = await session.scalar(
                    select(ReservationDeadLetterRecord).where(
                        ReservationDeadLetterRecord.event_id == "bad-event-1"
                    )
                )
                assert letter is not None
                assert "email" not in str(letter.payload)
                outbox_rows = (
                    await session.scalars(select(ReservationOutboxRecord))
                ).all()
                assert outbox_rows[0].delivered_at is not None
        finally:
            await engine.dispose()

    asyncio.run(exercise())
