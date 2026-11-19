"""Celery adapters for Reservations outbox delivery and expiry."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_booking.modules.inventory.adapters.clock import SystemClock
from flight_booking.modules.inventory.adapters.persistence.session import (
    DATABASE_URL as INVENTORY_DATABASE_URL,
)
from flight_booking.modules.payments.adapters.commands import SqlAlchemyPaymentCommands
from flight_booking.modules.payments.adapters.persistence.session import (
    DATABASE_URL as PAYMENTS_DATABASE_URL,
)
from flight_booking.modules.reservations.adapters.inventory import (
    InventoryCommandsAdapter,
)
from flight_booking.modules.reservations.adapters.persistence.outbox import (
    SqlAlchemyReservationOutboxRepository,
)
from flight_booking.modules.reservations.adapters.persistence.repository import (
    SqlAlchemyReservationRepository,
)
from flight_booking.modules.reservations.adapters.persistence.session import (
    DATABASE_URL,
)
from flight_booking.modules.reservations.adapters.worker.celery_app import celery_app
from flight_booking.modules.reservations.application.expire_reservations import (
    ExpireReservations,
)
from flight_booking.shared.messaging.redis_streams import (
    dispatch_outbox_batch,
)
from flight_booking.shared.observability import run_logged_job


async def publish_reservations_outbox_batch() -> int:
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        return await dispatch_outbox_batch(
            SqlAlchemyReservationOutboxRepository(sessions),
            consumer="reservations-redis-stream-publisher",
        )
    finally:
        await engine.dispose()


@celery_app.task(name="reservations.publish_outbox")
def publish_outbox() -> int:
    return run_logged_job("reservations", "publish_outbox", publish_reservations_outbox_batch)


async def expire_due_reservations_batch() -> int:
    reservation_engine = create_async_engine(
        DATABASE_URL, pool_pre_ping=True, hide_parameters=True
    )
    inventory_engine = create_async_engine(
        INVENTORY_DATABASE_URL, pool_pre_ping=True, hide_parameters=True
    )
    payments_engine = create_async_engine(
        PAYMENTS_DATABASE_URL, pool_pre_ping=True, hide_parameters=True
    )
    reservation_sessions = async_sessionmaker(
        reservation_engine, expire_on_commit=False
    )
    inventory_sessions = async_sessionmaker(inventory_engine, expire_on_commit=False)
    payments_sessions = async_sessionmaker(payments_engine, expire_on_commit=False)
    try:
        result = await ExpireReservations(
            SqlAlchemyReservationRepository(reservation_sessions),
            InventoryCommandsAdapter(inventory_sessions),
            SystemClock(),
            payments=SqlAlchemyPaymentCommands(payments_sessions),
        ).run_once()
        return result.expired + result.compensation_resolved
    finally:
        await payments_engine.dispose()
        await inventory_engine.dispose()
        await reservation_engine.dispose()


@celery_app.task(name="reservations.expire_due")
def expire_due() -> int:
    return run_logged_job("reservations", "expire_due", expire_due_reservations_batch)
