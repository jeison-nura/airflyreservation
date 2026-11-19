"""Transactional repository for a reservation and its saga progress."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flight_booking.modules.reservations.adapters.persistence.models import (
    PassengerDetailsRecord,
    RequestIdempotencyRecord,
    ReservationNotificationRecord,
    ReservationOutboxRecord,
    ReservationRecord,
    ReservationSagaRecord,
    SagaOperationRecord,
)
from flight_booking.modules.reservations.application.ports import (
    ConcurrentReservationWrite,
    IdempotencyKeyConflict,
    ReservationNotFound,
    ReservationNotification,
    ReservationRepository,
    ReservationWriteConflict,
)
from flight_booking.modules.reservations.domain.models import (
    CompensationStatus,
    Reservation,
    ReservationAggregate,
    ReservationConflict,
    ReservationSaga,
    ReservationStatus,
    SagaStep,
)


def _stored_instant(value: datetime, *, sqlite: bool) -> datetime:
    # SQLite does not preserve timezone information in DateTime(timezone=True).
    if sqlite and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class SqlAlchemyReservationRepository(ReservationRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, aggregate: ReservationAggregate) -> ReservationAggregate:
        reservation, saga = aggregate.reservation, aggregate.saga
        if (
            reservation.version != 1
            or reservation.status is not ReservationStatus.PENDING
        ):
            raise ValueError("New reservations must start PENDING at version 1")
        if saga.step is not SagaStep.HOLD_REQUESTED:
            raise ValueError("New sagas must start at HOLD_REQUESTED")
        try:
            async with self._session_factory() as session, session.begin():
                session.add(
                    ReservationRecord(
                        id=reservation.id,
                        flight_id=reservation.flight_id,
                        seat_number=reservation.seat_number,
                        status=reservation.status.value,
                        created_at=reservation.created_at.astimezone(UTC),
                        expires_at=reservation.expires_at.astimezone(UTC),
                        version=reservation.version,
                        booking_code=None,
                        failure_reason=None,
                        amount=reservation.amount,
                        currency=reservation.currency,
                    )
                )
                # These tables are mapped without ORM relationships, so the
                # unit of work cannot infer their insert dependency from the
                # foreign keys alone. Persist the parent before FK children.
                await session.flush()
                session.add(
                    ReservationSagaRecord(
                        reservation_id=saga.reservation_id,
                        correlation_id=saga.correlation_id,
                        step=saga.step.value,
                        compensation_status=saga.compensation_status.value,
                        payment_attempt_ref=saga.payment_attempt_ref,
                    )
                )
                await session.flush()
        except IntegrityError as exc:
            raise ReservationWriteConflict(
                "Reservation identity already exists"
            ) from exc
        return aggregate

    async def create_booking(
        self,
        aggregate: ReservationAggregate,
        *,
        full_name: str,
        email: str,
        access_credential_hash: str,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[ReservationAggregate, bool]:
        reservation, saga = aggregate.reservation, aggregate.saga
        try:
            async with self._session_factory() as session, session.begin():
                previous = await session.get(
                    RequestIdempotencyRecord, ("create", idempotency_key)
                )
                if previous is not None:
                    if previous.request_hash != request_hash:
                        raise IdempotencyKeyConflict(
                            "Idempotency key used with another request"
                        )
                    existing = await self._get_in_session(
                        session, previous.reservation_id
                    )
                    if existing is None:
                        raise RuntimeError("Idempotency record has no reservation")
                    return existing, True

                session.add(
                    ReservationRecord(
                        id=reservation.id,
                        flight_id=reservation.flight_id,
                        seat_number=reservation.seat_number,
                        status=reservation.status.value,
                        created_at=reservation.created_at.astimezone(UTC),
                        expires_at=reservation.expires_at.astimezone(UTC),
                        version=reservation.version,
                        booking_code=None,
                        failure_reason=None,
                        access_credential_hash=access_credential_hash,
                        amount=reservation.amount,
                        currency=reservation.currency,
                    )
                )
                # Without ORM relationships, explicitly insert the parent
                # before adding rows with foreign keys to it.
                await session.flush()
                session.add(
                    ReservationSagaRecord(
                        reservation_id=saga.reservation_id,
                        correlation_id=saga.correlation_id,
                        step=saga.step.value,
                        compensation_status=saga.compensation_status.value,
                        payment_attempt_ref=saga.payment_attempt_ref,
                    )
                )
                session.add(
                    PassengerDetailsRecord(
                        reservation_id=reservation.id,
                        full_name=full_name,
                        email=email,
                    )
                )
                session.add(
                    RequestIdempotencyRecord(
                        operation="create",
                        key=idempotency_key,
                        request_hash=request_hash,
                        reservation_id=reservation.id,
                        created_at=reservation.created_at.astimezone(UTC),
                    )
                )
                hold_payload = {
                    "flightId": reservation.flight_id,
                    "seatNumber": reservation.seat_number,
                    "reservationId": reservation.id,
                    "expiresAt": reservation.expires_at.isoformat(),
                }
                session.add(
                    SagaOperationRecord(
                        id=uuid4().hex,
                        reservation_id=reservation.id,
                        destination="inventory",
                        operation="hold",
                        idempotency_key=f"reservation-{reservation.id}",
                        request_hash=hashlib.sha256(
                            json.dumps(
                                hold_payload,
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode()
                        ).hexdigest(),
                        state="PENDING",
                        outcome=None,
                        attempts=0,
                        created_at=reservation.created_at.astimezone(UTC),
                        updated_at=reservation.created_at.astimezone(UTC),
                    )
                )
                initial_notification_id = uuid4().hex
                session.add(
                    ReservationNotificationRecord(
                        notification_id=initial_notification_id,
                        reservation_id=reservation.id,
                        sequence=1,
                        status=reservation.status.value,
                        occurred_at=reservation.created_at.astimezone(UTC),
                    )
                )
                session.add(
                    ReservationOutboxRecord(
                        event_id=uuid4().hex,
                        reservation_id=reservation.id,
                        event_type="ReservationCreated",
                        schema_version=1,
                        payload={
                            "reservationId": reservation.id,
                            "status": reservation.status.value,
                            "sequence": 1,
                            "notificationId": initial_notification_id,
                            "flightId": reservation.flight_id,
                            "seatNumber": reservation.seat_number,
                            "expiresAt": reservation.expires_at.isoformat(),
                        },
                        correlation_id=saga.correlation_id,
                        causation_id=uuid4().hex,
                        occurred_at=reservation.created_at.astimezone(UTC),
                        attempts=0,
                    )
                )
                await session.flush()
        except IntegrityError as exc:
            async with self._session_factory() as session:
                previous = await session.get(
                    RequestIdempotencyRecord, ("create", idempotency_key)
                )
                if previous is not None:
                    if previous.request_hash != request_hash:
                        raise IdempotencyKeyConflict(
                            "Idempotency key used with another request"
                        ) from exc
                    existing = await self._get_in_session(
                        session, previous.reservation_id
                    )
                    if existing is not None:
                        return existing, True
            raise ReservationWriteConflict(
                "Reservation identity already exists"
            ) from exc
        return aggregate, False

    async def get_access_credential_hash(self, reservation_id: str) -> str | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(ReservationRecord.access_credential_hash).where(
                    ReservationRecord.id == reservation_id
                )
            )

    async def find_due(self, now: datetime, limit: int) -> list[str]:
        if limit < 1:
            raise ValueError("Limit must be positive")
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(ReservationRecord.id)
                .outerjoin(
                    ReservationSagaRecord,
                    ReservationSagaRecord.reservation_id == ReservationRecord.id,
                )
                .where(
                    (
                        (ReservationRecord.status == ReservationStatus.PENDING.value)
                        & (ReservationRecord.expires_at <= now)
                    )
                    | (
                        ReservationSagaRecord.step
                        == SagaStep.COMPENSATION_PENDING.value
                    )
                )
                .order_by(ReservationRecord.expires_at, ReservationRecord.id)
                .limit(limit)
            )
            return list(rows)

    async def claim_idempotency(
        self,
        operation: str,
        key: str,
        request_hash: str,
        reservation_id: str,
        created_at: datetime,
    ) -> bool:
        try:
            async with self._session_factory() as session, session.begin():
                existing = await session.get(RequestIdempotencyRecord, (operation, key))
                if existing is not None:
                    if (
                        existing.request_hash != request_hash
                        or existing.reservation_id != reservation_id
                    ):
                        raise IdempotencyKeyConflict(
                            "Idempotency key used with another request"
                        )
                    return False
                session.add(
                    RequestIdempotencyRecord(
                        operation=operation,
                        key=key,
                        request_hash=request_hash,
                        reservation_id=reservation_id,
                        created_at=created_at.astimezone(UTC),
                    )
                )
                await session.flush()
                return True
        except IntegrityError as exc:
            async with self._session_factory() as session:
                existing = await session.get(RequestIdempotencyRecord, (operation, key))
            if (
                existing is None
                or existing.request_hash != request_hash
                or existing.reservation_id != reservation_id
            ):
                raise IdempotencyKeyConflict(
                    "Idempotency key used with another request"
                ) from exc
            return False

    async def get_notifications_after(
        self, reservation_id: str, after_sequence: int, *, limit: int = 100
    ) -> list[ReservationNotification]:
        if after_sequence < 0 or limit < 1 or limit > 500:
            raise ValueError("Invalid notification cursor or limit")
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(ReservationNotificationRecord)
                .where(
                    ReservationNotificationRecord.reservation_id == reservation_id,
                    ReservationNotificationRecord.sequence > after_sequence,
                )
                .order_by(ReservationNotificationRecord.sequence)
                .limit(limit)
            )
            return [
                ReservationNotification(
                    notification_id=row.notification_id,
                    sequence=row.sequence,
                    status=row.status,
                    occurred_at=_stored_instant(
                        row.occurred_at,
                        sqlite=session.get_bind().dialect.name == "sqlite",
                    ),
                )
                for row in rows
            ]

    async def get_notification_sequence(self, reservation_id: str) -> int:
        async with self._session_factory() as session:
            sequence = await session.scalar(
                select(
                    func.coalesce(
                        func.max(ReservationNotificationRecord.sequence), 0
                    )
                ).where(
                    ReservationNotificationRecord.reservation_id == reservation_id
                )
            )
            return int(sequence or 0)

    async def get(self, reservation_id: str) -> ReservationAggregate | None:
        async with self._session_factory() as session:
            return await self._get_in_session(session, reservation_id)

    @staticmethod
    async def _get_in_session(
        session: AsyncSession, reservation_id: str
    ) -> ReservationAggregate | None:
        pair = (
            await session.execute(
                select(ReservationRecord, ReservationSagaRecord)
                .join(
                    ReservationSagaRecord,
                    ReservationSagaRecord.reservation_id == ReservationRecord.id,
                )
                .where(ReservationRecord.id == reservation_id)
            )
        ).one_or_none()
        if pair is None:
            return None
        reservation, saga = pair
        sqlite = session.get_bind().dialect.name == "sqlite"
        return ReservationAggregate(
            Reservation(
                reservation.id,
                reservation.flight_id,
                reservation.seat_number,
                ReservationStatus(reservation.status),
                _stored_instant(reservation.created_at, sqlite=sqlite),
                _stored_instant(reservation.expires_at, sqlite=sqlite),
                reservation.version,
                reservation.booking_code,
                reservation.failure_reason,
                reservation.amount,
                reservation.currency,
            ),
            ReservationSaga(
                saga.reservation_id,
                saga.correlation_id,
                SagaStep(saga.step),
                CompensationStatus(saga.compensation_status),
                saga.payment_attempt_ref,
            ),
        )

    async def save(
        self, aggregate: ReservationAggregate, *, expected_version: int
    ) -> ReservationAggregate:
        reservation, saga = aggregate.reservation, aggregate.saga
        if reservation.version != expected_version or expected_version < 1:
            raise ConcurrentReservationWrite("Reservation version is stale")
        try:
            async with self._session_factory() as session, session.begin():
                record = await session.scalar(
                    select(ReservationRecord)
                    .where(ReservationRecord.id == reservation.id)
                    .with_for_update()
                )
                if record is None:
                    raise ReservationNotFound("Reservation not found")
                if record.version != expected_version:
                    raise ConcurrentReservationWrite("Reservation version is stale")
                if record.status != ReservationStatus.PENDING.value and (
                    record.status != reservation.status.value
                    or record.booking_code != reservation.booking_code
                    or record.failure_reason != reservation.failure_reason
                ):
                    raise ReservationConflict(
                        "A terminal reservation cannot change outcome"
                    )
                sqlite = session.get_bind().dialect.name == "sqlite"
                if (
                    record.flight_id != reservation.flight_id
                    or record.seat_number != reservation.seat_number
                    or _stored_instant(record.created_at, sqlite=sqlite)
                    != reservation.created_at.astimezone(UTC)
                    or _stored_instant(record.expires_at, sqlite=sqlite)
                    != reservation.expires_at.astimezone(UTC)
                    or record.amount != reservation.amount
                    or record.currency != reservation.currency
                ):
                    raise ValueError(
                        "Cannot change reservation identity, expiry or price snapshot"
                    )
                saga_record = await session.get(ReservationSagaRecord, reservation.id)
                if saga_record is None:
                    raise RuntimeError("Reservation saga is missing")
                if saga_record.correlation_id != saga.correlation_id:
                    raise ValueError("Cannot change saga correlation")
                next_version = await session.scalar(
                    update(ReservationRecord)
                    .where(
                        ReservationRecord.id == reservation.id,
                        ReservationRecord.version == expected_version,
                    )
                    .values(
                        status=reservation.status.value,
                        booking_code=reservation.booking_code,
                        failure_reason=reservation.failure_reason,
                        version=expected_version + 1,
                    )
                    .returning(ReservationRecord.version)
                )
                if next_version is None:
                    raise ConcurrentReservationWrite("Reservation version is stale")
                status_changed = record.status != reservation.status.value
                step_changed = saga_record.step != saga.step.value
                previous_step = saga_record.step
                saga_record.step = saga.step.value
                saga_record.compensation_status = saga.compensation_status.value
                saga_record.payment_attempt_ref = saga.payment_attempt_ref
                occurred_at = datetime.now(UTC)
                if status_changed:
                    current_sequence = await session.scalar(
                        select(
                            func.coalesce(
                                func.max(ReservationNotificationRecord.sequence), 0
                            )
                        ).where(
                            ReservationNotificationRecord.reservation_id
                            == reservation.id
                        )
                    )
                    sequence = int(current_sequence or 0) + 1
                    session.add(
                        ReservationNotificationRecord(
                            notification_id=(notification_id := uuid4().hex),
                            reservation_id=reservation.id,
                            sequence=sequence,
                            status=reservation.status.value,
                            occurred_at=occurred_at,
                        )
                    )
                    session.add(
                        ReservationOutboxRecord(
                            event_id=uuid4().hex,
                            reservation_id=reservation.id,
                            event_type="ReservationStatusChanged",
                            schema_version=1,
                            payload={
                                "reservationId": reservation.id,
                                "status": reservation.status.value,
                                "sequence": sequence,
                                "notificationId": notification_id,
                                "bookingCode": reservation.booking_code,
                                "failureReason": reservation.failure_reason,
                            },
                            correlation_id=saga.correlation_id,
                            causation_id=uuid4().hex,
                            occurred_at=occurred_at,
                            attempts=0,
                        )
                    )
                elif step_changed:
                    if (
                        previous_step == SagaStep.HOLD_REQUESTED.value
                        and saga.step is SagaStep.HOLD_OBTAINED
                    ):
                        operation_state = "SUCCEEDED"
                        operation_outcome = {"status": "HELD"}
                    elif (
                        previous_step == SagaStep.HOLD_REQUESTED.value
                        and saga.step is SagaStep.DONE
                    ):
                        operation_state = "REJECTED"
                        operation_outcome = {"reason": reservation.failure_reason}
                    else:
                        operation_state = None
                        operation_outcome = None
                    if operation_state is not None:
                        operation = await session.scalar(
                            select(SagaOperationRecord)
                            .where(
                                SagaOperationRecord.reservation_id
                                == reservation.id,
                                SagaOperationRecord.destination == "inventory",
                                SagaOperationRecord.operation == "hold",
                            )
                            .with_for_update()
                        )
                        if operation is not None:
                            operation.state = operation_state
                            operation.outcome = operation_outcome
                            operation.attempts += 1
                            operation.updated_at = occurred_at
                    session.add(
                        ReservationOutboxRecord(
                            event_id=uuid4().hex,
                            reservation_id=reservation.id,
                            event_type="ReservationSagaProgressed",
                            schema_version=1,
                            payload={
                                "reservationId": reservation.id,
                                "status": reservation.status.value,
                                "step": saga.step.value,
                            },
                            correlation_id=saga.correlation_id,
                            causation_id=uuid4().hex,
                            occurred_at=occurred_at,
                            attempts=0,
                        )
                    )
                await session.flush()
        except IntegrityError as exc:
            raise ReservationWriteConflict(
                "Reservation outcome conflicts with another reservation"
            ) from exc
        return ReservationAggregate(replace(reservation, version=next_version), saga)
