from datetime import UTC, datetime, timedelta

import pytest

from flight_booking.modules.inventory.domain.models import FlightStatus, SeatStatus
from flight_booking.modules.inventory.domain.seat_allocation import (
    HoldExpired,
    SeatAllocation,
    SeatConflict,
)

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)
EXPIRY = NOW + timedelta(minutes=10)


def available(*, flight_status=FlightStatus.ON_TIME):
    return SeatAllocation("flight-204", "1A", SeatStatus.AVAILABLE, flight_status)


def held(*, owner="reservation-1", expiry=EXPIRY):
    return available().hold(owner, expiry, NOW)


def test_hold_sets_owner_and_expiry_without_changing_original():
    seat = available()
    result = seat.hold("reservation-1", EXPIRY, NOW)

    assert seat.status is SeatStatus.AVAILABLE
    assert result.status is SeatStatus.HELD
    assert result.reservation_id == "reservation-1"
    assert result.hold_expires_at == EXPIRY


def test_hold_rejects_cancelled_unavailable_and_held_by_another_reservation():
    with pytest.raises(SeatConflict):
        available(flight_status=FlightStatus.CANCELLED).hold("reservation-1", EXPIRY, NOW)
    with pytest.raises(SeatConflict):
        SeatAllocation("flight-204", "1A", SeatStatus.UNAVAILABLE, FlightStatus.ON_TIME).hold(
            "reservation-1", EXPIRY, NOW
        )
    with pytest.raises(SeatConflict):
        held().hold("reservation-2", EXPIRY, NOW)


def test_repeated_hold_with_same_owner_and_expiry_is_idempotent_but_cannot_extend():
    seat = held()
    assert seat.hold("reservation-1", EXPIRY, NOW) is seat
    with pytest.raises(SeatConflict):
        seat.hold("reservation-1", EXPIRY + timedelta(minutes=1), NOW)


def test_expired_hold_can_be_replaced_but_not_renewed_by_replaying_old_deadline():
    expired = held(expiry=NOW + timedelta(seconds=1))
    later = NOW + timedelta(seconds=1)

    with pytest.raises(ValueError):
        expired.hold("reservation-1", expired.hold_expires_at, later)
    result = expired.hold("reservation-2", later + timedelta(minutes=5), later)
    assert result.reservation_id == "reservation-2"
    assert result.status is SeatStatus.HELD


def test_confirm_requires_current_owner_and_unexpired_hold():
    seat = held()
    booked = seat.confirm("reservation-1", NOW)
    assert booked.status is SeatStatus.BOOKED
    assert booked.reservation_id == "reservation-1"
    assert booked.hold_expires_at is None
    assert booked.confirm("reservation-1", NOW) is booked
    with pytest.raises(SeatConflict):
        seat.confirm("reservation-2", NOW)
    with pytest.raises(HoldExpired):
        seat.confirm("reservation-1", EXPIRY)
    with pytest.raises(SeatConflict):
        available().confirm("reservation-1", NOW)
    cancelled = SeatAllocation(
        "flight-204",
        "1A",
        SeatStatus.HELD,
        FlightStatus.CANCELLED,
        reservation_id="reservation-1",
        hold_expires_at=EXPIRY,
    )
    with pytest.raises(SeatConflict):
        cancelled.confirm("reservation-1", NOW)


def test_release_only_clears_the_owning_reservation_and_never_unavailable():
    for seat in (held(), held().confirm("reservation-1", NOW)):
        released = seat.release("reservation-1")
        assert released.status is SeatStatus.AVAILABLE
        assert released.reservation_id is None
        assert released.hold_expires_at is None
        with pytest.raises(SeatConflict):
            seat.release("reservation-2")
    assert available().release("reservation-1") == available()
    with pytest.raises(SeatConflict):
        SeatAllocation("flight-204", "1A", SeatStatus.UNAVAILABLE, FlightStatus.ON_TIME).release(
            "reservation-1"
        )


def test_expire_releases_only_elapsed_holds():
    seat = held()
    assert seat.expire(NOW) is seat
    assert seat.expire(EXPIRY).status is SeatStatus.AVAILABLE
    assert seat.confirm("reservation-1", NOW).expire(EXPIRY).status is SeatStatus.BOOKED


def test_invalid_owner_deadline_and_inconsistent_state_are_rejected():
    with pytest.raises(ValueError):
        available().hold("", EXPIRY, NOW)
    with pytest.raises(ValueError):
        available().hold("  ", EXPIRY, NOW)
    with pytest.raises(ValueError):
        available().hold("reservation-1", NOW, NOW)
    with pytest.raises(ValueError):
        available().hold("reservation-1", EXPIRY.replace(tzinfo=None), NOW)
    with pytest.raises(ValueError):
        available().hold("reservation-1", EXPIRY, NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        SeatAllocation("flight-204", "1A", SeatStatus.HELD, FlightStatus.ON_TIME)
    with pytest.raises(ValueError):
        SeatAllocation("f" * 65, "1A", SeatStatus.AVAILABLE, FlightStatus.ON_TIME)
    with pytest.raises(ValueError):
        SeatAllocation(
            "flight-204",
            "1A",
            SeatStatus.AVAILABLE,
            FlightStatus.ON_TIME,
            reservation_id="reservation-1",
        )
