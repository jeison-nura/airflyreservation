"""Expire reservations and resume Inventory compensation idempotently."""

from dataclasses import dataclass

from flight_booking.modules.reservations.application.confirm_reservation import (
    PaymentUnavailable,
)
from flight_booking.modules.reservations.application.create_reservation import (
    ReservationClock,
    SeatDoesNotExist,
    SeatUnavailable,
)
from flight_booking.modules.reservations.application.ports import (
    ConcurrentReservationWrite,
    InventoryCommands,
    PaymentCommands,
    ReservationRepository,
)
from flight_booking.modules.reservations.domain.models import (
    ReservationAggregate,
    ReservationStatus,
    SagaStep,
)
from flight_booking.shared.observability import log_event


@dataclass(frozen=True)
class ExpiryBatchResult:
    expired: int = 0
    compensation_resolved: int = 0
    compensation_pending: int = 0


class ExpireReservations:
    def __init__(
        self,
        repository: ReservationRepository,
        inventory: InventoryCommands,
        clock: ReservationClock,
        payments: PaymentCommands | None = None,
    ) -> None:
        self._repository = repository
        self._inventory = inventory
        self._clock = clock
        self._payments = payments

    async def run_once(self, *, limit: int = 50) -> ExpiryBatchResult:
        if limit < 1:
            raise ValueError("Limit must be positive")
        ids = await self._repository.find_due(self._clock.now(), limit)
        expired = resolved = pending = 0
        for reservation_id in ids:
            aggregate = await self._repository.get(reservation_id)
            if aggregate is None:
                continue
            if aggregate.reservation.status is ReservationStatus.PENDING:
                changed = aggregate.reservation.expire(self._clock.now())
                if (
                    changed == aggregate.reservation
                    and aggregate.saga.step is not SagaStep.COMPENSATION_PENDING
                ):
                    continue
                if changed != aggregate.reservation:
                    aggregate = ReservationAggregate(
                        changed,
                        aggregate.saga.advance(SagaStep.COMPENSATION_PENDING),
                    )
                    try:
                        aggregate = await self._repository.save(
                            aggregate,
                            expected_version=aggregate.reservation.version,
                        )
                        expired += 1
                        log_event(
                            "reservations", "reservation_expired",
                            correlation_id=aggregate.saga.correlation_id,
                        )
                    except ConcurrentReservationWrite:
                        continue
            if (
                aggregate.saga.step is not SagaStep.COMPENSATION_PENDING
            ):
                continue
            if not await self._compensate_payment(aggregate):
                log_event(
                    "reservations", "compensation_pending", level="WARNING",
                    correlation_id=aggregate.saga.correlation_id, operation="payment",
                )
                pending += 1
                continue
            try:
                await self._inventory.release(
                    aggregate.reservation.flight_id,
                    aggregate.reservation.seat_number,
                    aggregate.reservation.id,
                    correlation_id=aggregate.saga.correlation_id,
                )
            except (SeatUnavailable, SeatDoesNotExist):
                log_event(
                    "reservations", "compensation_pending", level="WARNING",
                    correlation_id=aggregate.saga.correlation_id, operation="release_seat",
                )
                pending += 1
                continue
            completed = ReservationAggregate(
                (
                    aggregate.reservation.fail(
                        "PURCHASE_FAILED", compensation_resolved=True
                    )
                    if aggregate.reservation.status is ReservationStatus.PENDING
                    else aggregate.reservation
                ),
                aggregate.saga.advance(SagaStep.DONE),
            )
            try:
                await self._repository.save(
                    completed,
                    expected_version=aggregate.reservation.version,
                )
                resolved += 1
                log_event(
                    "reservations", "compensation_resolved",
                    correlation_id=aggregate.saga.correlation_id,
                )
            except ConcurrentReservationWrite:
                pending += 1
        return ExpiryBatchResult(expired, resolved, pending)

    async def _compensate_payment(
        self, aggregate: ReservationAggregate
    ) -> bool:
        attempt_ref = aggregate.saga.payment_attempt_ref
        if attempt_ref is None:
            return True
        if self._payments is None:
            return False
        try:
            payment = await self._payments.query_attempt(
                payment_attempt_ref=attempt_ref,
                correlation_id=aggregate.saga.correlation_id,
            )
            if payment.payment_attempt_ref != attempt_ref:
                return False
            if payment.status == "CAPTURED":
                result = await self._payments.refund(
                    payment_attempt_ref=attempt_ref,
                    idempotency_key=f"{aggregate.reservation.id}-refund",
                    correlation_id=aggregate.saga.correlation_id,
                )
                return result.status == "REFUNDED"
            if payment.status == "AUTHORIZED":
                result = await self._payments.void(
                    payment_attempt_ref=attempt_ref,
                    idempotency_key=f"{aggregate.reservation.id}-void",
                    correlation_id=aggregate.saga.correlation_id,
                )
                return result.status == "VOIDED"
            return payment.status in ("DENIED", "VOIDED", "REFUNDED")
        except PaymentUnavailable:
            return False
