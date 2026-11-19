from datetime import UTC, datetime, timedelta

import pytest

from flight_booking.modules.reservations.domain.models import (
    Reservation,
    ReservationAggregate,
    ReservationConflict,
    ReservationSaga,
    ReservationStatus,
    SagaStep,
)

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)
EXPIRES = NOW + timedelta(minutes=10)


def pending() -> Reservation:
    return Reservation.start("reservation-1", "flight-204", "1A", NOW, EXPIRES)


def test_reservation_requires_valid_identifiers_and_server_timestamps():
    assert pending().status is ReservationStatus.PENDING
    assert pending().version == 1
    with pytest.raises(ValueError):
        Reservation.start(" ", "flight-204", "1A", NOW, EXPIRES)
    with pytest.raises(ValueError):
        Reservation.start("r", "flight-204", "1A", NOW.replace(tzinfo=None), EXPIRES)
    with pytest.raises(ValueError):
        Reservation.start("r", "flight-204", "1A", NOW, NOW)


def test_confirm_requires_both_booking_and_capture_before_deadline():
    reservation = pending()
    with pytest.raises(ReservationConflict):
        reservation.confirm(
            NOW, booking_code="CODE-1", seat_booked=False, payment_captured=True
        )
    with pytest.raises(ReservationConflict):
        reservation.confirm(
            NOW, booking_code="CODE-1", seat_booked=True, payment_captured=False
        )
    with pytest.raises(ReservationConflict):
        reservation.confirm(
            EXPIRES, booking_code="CODE-1", seat_booked=True, payment_captured=True
        )

    confirmed = reservation.confirm(
        NOW, booking_code="CODE-1", seat_booked=True, payment_captured=True
    )
    assert (confirmed.status, confirmed.booking_code) == (
        ReservationStatus.CONFIRMED,
        "CODE-1",
    )
    assert confirmed.expire(EXPIRES) == confirmed
    assert confirmed.version == 1  # Only persistence advances the version.
    with pytest.raises(ReservationConflict):
        confirmed.fail("PAYMENT_DENIED", compensation_resolved=True)


def test_expiry_is_terminal_and_failure_needs_resolved_compensation():
    reservation = pending()
    assert reservation.expire(NOW) == reservation
    expired = reservation.expire(EXPIRES)
    assert expired.status is ReservationStatus.EXPIRED
    assert expired.expire(EXPIRES) == expired
    with pytest.raises(ReservationConflict):
        expired.confirm(
            EXPIRES, booking_code="CODE", seat_booked=True, payment_captured=True
        )
    with pytest.raises(ReservationConflict):
        reservation.fail("PAYMENT_DENIED", compensation_resolved=False)
    failed = reservation.fail("PAYMENT_DENIED", compensation_resolved=True)
    assert (failed.status, failed.failure_reason) == (
        ReservationStatus.FAILED,
        "PAYMENT_DENIED",
    )
    assert failed.expire(EXPIRES) == failed


def test_saga_rejects_skipped_steps_and_aggregate_requires_matching_identity():
    saga = ReservationSaga.start("reservation-1", "correlation-1")
    assert (
        saga.advance(SagaStep.HOLD_OBTAINED).advance(SagaStep.AUTHORIZING).step
        is SagaStep.AUTHORIZING
    )
    with pytest.raises(ReservationConflict):
        saga.advance(SagaStep.CAPTURING)
    assert ReservationAggregate(pending(), saga).reservation.id == saga.reservation_id
    with pytest.raises(ValueError):
        ReservationAggregate(pending(), ReservationSaga.start("other", "correlation-2"))
    with pytest.raises(ValueError):
        ReservationAggregate(pending().expire(EXPIRES), saga)
    with pytest.raises(ValueError):
        ReservationAggregate(
            pending().confirm(
                NOW, booking_code="CODE", seat_booked=True, payment_captured=True
            ),
            saga,
        )
