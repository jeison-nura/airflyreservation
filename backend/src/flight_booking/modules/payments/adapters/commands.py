"""Small persisted fake payment processor for the MVP."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flight_booking.modules.payments.adapters.persistence.models import (
    PaymentAttemptRecord,
)
from flight_booking.modules.payments.adapters.persistence.session import SessionFactory
from flight_booking.modules.payments.domain.models import PaymentConflict, PaymentStatus
from flight_booking.modules.reservations.application.ports import PaymentResult
from flight_booking.shared.observability import log_event


@contextmanager
def _observe_payment(operation: str, correlation_id: str) -> Iterator[None]:
    try:
        yield
    except Exception as exc:
        conflict = isinstance(exc, PaymentConflict)
        log_event(
            "payments", "payment_operation", correlation_id=correlation_id,
            level="WARNING" if conflict else "ERROR", operation=operation,
            outcome="conflict" if conflict else "error", error_type=type(exc).__name__,
        )
        raise


def _log_result(operation: str, correlation_id: str, result: PaymentResult) -> PaymentResult:
    log_event(
        "payments", "payment_operation", correlation_id=correlation_id,
        operation=operation, outcome=result.status,
        level="WARNING" if result.status in ("DENIED", "UNKNOWN") else "INFO",
    )
    return result


class SqlAlchemyPaymentCommands:
    """Approves valid authorizations and persists idempotent state transitions."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession] = SessionFactory
    ) -> None:
        self._session_factory = session_factory

    async def authorize(
        self,
        *,
        payment_attempt_ref: str,
        reservation_id: str,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> PaymentResult:
        with _observe_payment("authorize", correlation_id):
            result = await self._authorize(
                payment_attempt_ref, reservation_id, amount, currency, idempotency_key
            )
        return _log_result("authorize", correlation_id, result)

    async def _authorize(
        self,
        payment_attempt_ref: str,
        reservation_id: str,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
    ) -> PaymentResult:
        if amount <= 0 or len(currency) != 3:
            return PaymentResult("DENIED", payment_attempt_ref, "INVALID_AMOUNT")
        now = datetime.now(UTC)
        try:
            async with self._session_factory() as session, session.begin():
                attempt = await session.get(
                    PaymentAttemptRecord, payment_attempt_ref, with_for_update=True
                )
                if attempt is None:
                    attempt = PaymentAttemptRecord(
                        payment_attempt_ref=payment_attempt_ref,
                        reservation_id=reservation_id,
                        amount=amount,
                        currency=currency.upper(),
                        status=PaymentStatus.AUTHORIZED.value,
                        authorize_key=idempotency_key,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(attempt)
                    await session.flush()
                elif (
                    attempt.reservation_id != reservation_id
                    or attempt.amount != amount
                    or attempt.currency != currency.upper()
                    or attempt.authorize_key != idempotency_key
                ):
                    raise PaymentConflict("Payment attempt does not match request")
                return PaymentResult(attempt.status, payment_attempt_ref)
        except IntegrityError:
            # A concurrent duplicate authorization may have won the unique insert.
            async with self._session_factory() as session:
                attempt = await session.get(PaymentAttemptRecord, payment_attempt_ref)
            if attempt is None or attempt.authorize_key != idempotency_key:
                raise PaymentConflict("Idempotency key already used") from None
            return PaymentResult(attempt.status, payment_attempt_ref)

    async def capture(
        self,
        *,
        payment_attempt_ref: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> PaymentResult:
        return await self._change(
            payment_attempt_ref, idempotency_key, "capture", PaymentStatus.CAPTURED, correlation_id
        )

    async def void(
        self,
        *,
        payment_attempt_ref: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> PaymentResult:
        return await self._change(
            payment_attempt_ref, idempotency_key, "void", PaymentStatus.VOIDED, correlation_id
        )

    async def refund(
        self,
        *,
        payment_attempt_ref: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> PaymentResult:
        return await self._change(
            payment_attempt_ref, idempotency_key, "refund", PaymentStatus.REFUNDED, correlation_id
        )

    async def query_attempt(
        self, *, payment_attempt_ref: str, correlation_id: str
    ) -> PaymentResult:
        with _observe_payment("query", correlation_id):
            async with self._session_factory() as session:
                attempt = await session.get(PaymentAttemptRecord, payment_attempt_ref)
        result = PaymentResult(attempt.status if attempt else "UNKNOWN", payment_attempt_ref)
        return _log_result("query", correlation_id, result)

    async def _change(
        self,
        payment_attempt_ref: str,
        idempotency_key: str,
        operation: str,
        target: PaymentStatus,
        correlation_id: str,
    ) -> PaymentResult:
        with _observe_payment(operation, correlation_id):
            result = await self._transition(payment_attempt_ref, idempotency_key, operation, target)
        return _log_result(operation, correlation_id, result)

    async def _transition(
        self,
        payment_attempt_ref: str,
        idempotency_key: str,
        operation: str,
        target: PaymentStatus,
    ) -> PaymentResult:
        key_field = f"{operation}_key"
        allowed_from = {
            "capture": PaymentStatus.AUTHORIZED,
            "void": PaymentStatus.AUTHORIZED,
            "refund": PaymentStatus.CAPTURED,
        }
        async with self._session_factory() as session, session.begin():
            attempt = await session.scalar(
                select(PaymentAttemptRecord)
                .where(PaymentAttemptRecord.payment_attempt_ref == payment_attempt_ref)
                .with_for_update()
            )
            if attempt is None:
                return PaymentResult("UNKNOWN", payment_attempt_ref)
            prior_key = getattr(attempt, key_field)
            if prior_key is not None and prior_key != idempotency_key:
                raise PaymentConflict("Operation already used with another key")
            if attempt.status == target.value:
                setattr(attempt, key_field, idempotency_key)
                return PaymentResult(target.value, payment_attempt_ref)
            if attempt.status != allowed_from[operation].value:
                raise PaymentConflict(f"Cannot {operation} payment in {attempt.status}")
            setattr(attempt, key_field, idempotency_key)
            attempt.status = target.value
            attempt.updated_at = datetime.now(UTC)
            await session.flush()
            return PaymentResult(target.value, payment_attempt_ref)
