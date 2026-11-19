"""Persistable purchase orchestration up to the Payments adapter boundary."""

import hashlib
import json
from dataclasses import dataclass, replace
from uuid import uuid4

from flight_booking.modules.reservations.application.create_reservation import (
    ReservationClock,
    SeatDoesNotExist,
    SeatUnavailable,
)
from flight_booking.modules.reservations.application.ports import (
    ConcurrentReservationWrite,
    InventoryCommands,
    PaymentCommands,
    PaymentResult,
    ReservationRepository,
)
from flight_booking.modules.reservations.domain.models import (
    ReservationAggregate,
    ReservationConflict,
    ReservationStatus,
    SagaStep,
)
from flight_booking.shared.observability import log_event


class PaymentUnavailable(Exception):
    """Payment result is uncertain; retry or reconcile the same attempt."""


@dataclass(frozen=True)
class ConfirmReservationResult:
    aggregate: ReservationAggregate
    pending: bool


class ConfirmReservation:
    def __init__(
        self,
        repository: ReservationRepository,
        inventory: InventoryCommands,
        payments: PaymentCommands,
        clock: ReservationClock,
    ) -> None:
        self._repository = repository
        self._inventory = inventory
        self._payments = payments
        self._clock = clock

    async def execute(
        self, reservation_id: str, *, idempotency_key: str
    ) -> ConfirmReservationResult:
        aggregate = await self._repository.get(reservation_id)
        if aggregate is None:
            raise ReservationConflict("Reservation not found")
        request_hash = hashlib.sha256(
            json.dumps(
                {"reservationId": reservation_id},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        first_request = await self._repository.claim_idempotency(
            "confirm",
            idempotency_key,
            request_hash,
            reservation_id,
            self._clock.now(),
        )
        if not first_request and aggregate.reservation.status in (
            ReservationStatus.CONFIRMED,
            ReservationStatus.FAILED,
            ReservationStatus.EXPIRED,
        ):
            return ConfirmReservationResult(aggregate, pending=False)
        if aggregate.reservation.status is ReservationStatus.CONFIRMED:
            return ConfirmReservationResult(aggregate, pending=False)
        if aggregate.reservation.status is not ReservationStatus.PENDING:
            raise ReservationConflict("Reservation is not pending")
        if self._clock.now() >= aggregate.reservation.expires_at:
            raise ReservationConflict("Reservation expired")
        if aggregate.reservation.amount is None or aggregate.reservation.currency is None:
            raise ReservationConflict("Reservation price snapshot is missing")

        if aggregate.saga.step is SagaStep.HOLD_OBTAINED:
            saga = replace(
                aggregate.saga.advance(SagaStep.AUTHORIZING),
                payment_attempt_ref=uuid4().hex,
            )
            aggregate = await self._save(
                ReservationAggregate(aggregate.reservation, saga), aggregate
            )

        if aggregate.saga.step is SagaStep.AUTHORIZING:
            attempt_ref = aggregate.saga.payment_attempt_ref
            if attempt_ref is None:
                raise RuntimeError("Authorization step has no payment attempt reference")
            try:
                outcome = await self._payments.authorize(
                    payment_attempt_ref=attempt_ref,
                    reservation_id=reservation_id,
                    amount=aggregate.reservation.amount,
                    currency=aggregate.reservation.currency,
                    idempotency_key=f"{reservation_id}-authorize",
                    correlation_id=aggregate.saga.correlation_id,
                )
            except PaymentUnavailable:
                return ConfirmReservationResult(aggregate, pending=True)
            self._validate_attempt(outcome, attempt_ref)
            if outcome.status == "DENIED":
                aggregate = await self._begin_compensation(aggregate)
                return await self._compensate(aggregate, "PAYMENT_DENIED")
            if outcome.status != "AUTHORIZED":
                return ConfirmReservationResult(aggregate, pending=True)
            aggregate = await self._save(
                ReservationAggregate(
                    aggregate.reservation,
                    aggregate.saga.advance(SagaStep.AUTHORIZED),
                ),
                aggregate,
            )

        if aggregate.saga.step is SagaStep.AUTHORIZED:
            aggregate = await self._save(
                ReservationAggregate(
                    aggregate.reservation,
                    aggregate.saga.advance(SagaStep.BOOKING_SEAT),
                ),
                aggregate,
            )

        if aggregate.saga.step is SagaStep.BOOKING_SEAT:
            try:
                await self._inventory.confirm(
                    aggregate.reservation.flight_id,
                    aggregate.reservation.seat_number,
                    reservation_id,
                    correlation_id=aggregate.saga.correlation_id,
                )
            except (SeatUnavailable, SeatDoesNotExist):
                aggregate = await self._begin_compensation(aggregate)
                return await self._compensate(aggregate, "SEAT_CONFIRMATION_FAILED")
            aggregate = await self._save(
                ReservationAggregate(
                    aggregate.reservation,
                    aggregate.saga.advance(SagaStep.SEAT_BOOKED),
                ),
                aggregate,
            )

        if aggregate.saga.step is SagaStep.SEAT_BOOKED:
            aggregate = await self._save(
                ReservationAggregate(
                    aggregate.reservation,
                    aggregate.saga.advance(SagaStep.CAPTURING),
                ),
                aggregate,
            )

        if aggregate.saga.step in (SagaStep.CAPTURING, SagaStep.RECONCILING):
            attempt_ref = aggregate.saga.payment_attempt_ref
            if attempt_ref is None:
                raise RuntimeError("Capture step has no payment attempt reference")
            try:
                if aggregate.saga.step is SagaStep.RECONCILING:
                    outcome = await self._payments.query_attempt(
                        payment_attempt_ref=attempt_ref,
                        correlation_id=aggregate.saga.correlation_id,
                    )
                    self._validate_attempt(outcome, attempt_ref)
                    if outcome.status == "CAPTURED":
                        return await self._confirm_captured(aggregate)
                    if outcome.status == "DENIED":
                        aggregate = await self._begin_compensation(aggregate)
                        return await self._compensate(
                            aggregate, "PAYMENT_CAPTURE_FAILED"
                        )
                    if outcome.status != "AUTHORIZED":
                        return ConfirmReservationResult(aggregate, pending=True)
                outcome = await self._payments.capture(
                    payment_attempt_ref=attempt_ref,
                    idempotency_key=f"{reservation_id}-capture",
                    correlation_id=aggregate.saga.correlation_id,
                )
            except PaymentUnavailable:
                if aggregate.saga.step is SagaStep.CAPTURING:
                    aggregate = await self._save(
                        ReservationAggregate(
                            aggregate.reservation,
                            aggregate.saga.advance(SagaStep.RECONCILING),
                        ),
                        aggregate,
                    )
                return ConfirmReservationResult(aggregate, pending=True)
            self._validate_attempt(outcome, attempt_ref)
            if outcome.status == "CAPTURED":
                return await self._confirm_captured(aggregate)
            if outcome.status == "DENIED":
                aggregate = await self._begin_compensation(aggregate)
                return await self._compensate(aggregate, "PAYMENT_CAPTURE_FAILED")
            if aggregate.saga.step is SagaStep.CAPTURING:
                aggregate = await self._save(
                    ReservationAggregate(
                        aggregate.reservation,
                        aggregate.saga.advance(SagaStep.RECONCILING),
                    ),
                    aggregate,
                )
            return ConfirmReservationResult(aggregate, pending=True)

        if aggregate.saga.step is SagaStep.COMPENSATION_PENDING:
            return await self._compensate(aggregate, "PURCHASE_FAILED")
        return ConfirmReservationResult(aggregate, pending=True)

    async def _confirm_captured(
        self, aggregate: ReservationAggregate
    ) -> ConfirmReservationResult:
        now = self._clock.now()
        if now >= aggregate.reservation.expires_at:
            expired = ReservationAggregate(
                aggregate.reservation.expire(now),
                aggregate.saga.advance(SagaStep.COMPENSATION_PENDING),
            )
            try:
                expired = await self._save(expired, aggregate)
            except ConcurrentReservationWrite:
                latest = await self._repository.get(aggregate.reservation.id)
                if latest is None or latest.reservation.status is not ReservationStatus.EXPIRED:
                    raise
                expired = latest
                if expired.saga.step is not SagaStep.COMPENSATION_PENDING:
                    expired = await self._begin_compensation(expired)
            return await self._compensate(expired, "PAYMENT_CAPTURE_AFTER_EXPIRY")
        booking_code = f"AF-{aggregate.reservation.id[:8].upper()}"
        confirmed = aggregate.reservation.confirm(
            now,
            booking_code=booking_code,
            seat_booked=True,
            payment_captured=True,
        )
        completed = ReservationAggregate(
            confirmed, aggregate.saga.advance(SagaStep.DONE)
        )
        saved = await self._save(completed, aggregate)
        return ConfirmReservationResult(saved, pending=False)

    async def _begin_compensation(
        self, aggregate: ReservationAggregate
    ) -> ReservationAggregate:
        if aggregate.saga.step is SagaStep.COMPENSATION_PENDING:
            return aggregate
        changed = ReservationAggregate(
            aggregate.reservation,
            aggregate.saga.advance(SagaStep.COMPENSATION_PENDING),
        )
        return await self._save(changed, aggregate)

    async def _compensate(
        self, aggregate: ReservationAggregate, failure_reason: str
    ) -> ConfirmReservationResult:
        attempt_ref = aggregate.saga.payment_attempt_ref
        if attempt_ref is not None:
            try:
                payment = await self._payments.query_attempt(
                    payment_attempt_ref=attempt_ref,
                    correlation_id=aggregate.saga.correlation_id,
                )
                self._validate_attempt(payment, attempt_ref)
                if payment.status == "CAPTURED":
                    payment = await self._payments.refund(
                        payment_attempt_ref=attempt_ref,
                        idempotency_key=f"{aggregate.reservation.id}-refund",
                        correlation_id=aggregate.saga.correlation_id,
                    )
                    if payment.status != "REFUNDED":
                        return ConfirmReservationResult(aggregate, pending=True)
                elif payment.status == "AUTHORIZED":
                    payment = await self._payments.void(
                        payment_attempt_ref=attempt_ref,
                        idempotency_key=f"{aggregate.reservation.id}-void",
                        correlation_id=aggregate.saga.correlation_id,
                    )
                    if payment.status != "VOIDED":
                        return ConfirmReservationResult(aggregate, pending=True)
                elif payment.status not in ("DENIED", "VOIDED", "REFUNDED"):
                    return ConfirmReservationResult(aggregate, pending=True)
            except PaymentUnavailable:
                return ConfirmReservationResult(aggregate, pending=True)

        try:
            await self._inventory.release(
                aggregate.reservation.flight_id,
                aggregate.reservation.seat_number,
                aggregate.reservation.id,
                correlation_id=aggregate.saga.correlation_id,
            )
        except SeatUnavailable:
            return ConfirmReservationResult(aggregate, pending=True)
        except SeatDoesNotExist:
            # There is no Inventory allocation owned by this reservation to retain.
            pass

        reservation = aggregate.reservation
        if reservation.status is ReservationStatus.PENDING:
            reservation = reservation.fail(
                failure_reason, compensation_resolved=True
            )
        completed = ReservationAggregate(
            reservation, aggregate.saga.advance(SagaStep.DONE)
        )
        saved = await self._save(completed, aggregate)
        return ConfirmReservationResult(saved, pending=False)

    async def _save(
        self,
        changed: ReservationAggregate,
        previous: ReservationAggregate,
    ) -> ReservationAggregate:
        saved = await self._repository.save(
            changed, expected_version=previous.reservation.version
        )
        log_event(
            "reservations", "reservation_saga_transition",
            correlation_id=saved.saga.correlation_id,
            status=saved.reservation.status.value, step=saved.saga.step.value,
        )
        return saved

    @staticmethod
    def _validate_attempt(result: PaymentResult, expected: str) -> None:
        if result.payment_attempt_ref != expected:
            raise RuntimeError("Payments returned a different attempt reference")
