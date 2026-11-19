"""Celery adapter for bounded Inventory expiry batches."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_booking.modules.inventory.adapters.clock import SystemClock
from flight_booking.modules.inventory.adapters.persistence.repository import (
    SqlAlchemySeatMutationRepository,
)
from flight_booking.modules.inventory.adapters.persistence.session import DATABASE_URL
from flight_booking.modules.inventory.adapters.persistence.worker_repository import (
    SqlAlchemyExpiredSeatRepository,
    SqlAlchemyOutboxRepository,
)
from flight_booking.modules.inventory.adapters.worker.celery_app import celery_app
from flight_booking.modules.inventory.application.expire_due_holds import ExpireDueHolds
from flight_booking.shared.messaging.redis_streams import (
    dispatch_outbox_batch,
)
from flight_booking.shared.observability import run_logged_job

BATCH_SIZE = 50


async def run_batch() -> int:
    # asyncio.run creates a new event loop per Celery task. Do not reuse the API's
    # global asyncpg pool across loops or forked worker processes.
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        return await ExpireDueHolds(
            SqlAlchemyExpiredSeatRepository(sessions),
            SqlAlchemySeatMutationRepository(sessions),
            SystemClock(),
        ).run_once(limit=BATCH_SIZE)
    finally:
        await engine.dispose()


@celery_app.task(name="inventory.expire_due_holds")
def expire_due_holds() -> int:
    return run_logged_job("inventory", "expire_due_holds", run_batch)


async def publish_inventory_outbox_batch() -> int:
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        return await dispatch_outbox_batch(
            SqlAlchemyOutboxRepository(sessions),
            consumer="inventory-redis-stream-publisher",
        )
    finally:
        await engine.dispose()


@celery_app.task(name="inventory.publish_outbox")
def publish_outbox() -> int:
    return run_logged_job("inventory", "publish_outbox", publish_inventory_outbox_batch)
