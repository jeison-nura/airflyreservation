import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from flight_booking.modules.inventory.application.manage_seats import (
    ConfirmSeat,
    ExpireSeat,
    HoldSeat,
    ReleaseSeat,
    SeatNotFound,
)
from flight_booking.modules.inventory.domain.models import FlightStatus, SeatStatus
from flight_booking.modules.inventory.domain.seat_allocation import (
    HoldExpired,
    SeatAllocation,
    SeatConflict,
)

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)
EXPIRY = NOW + timedelta(minutes=10)


class FixedClock:
    def __init__(self, now):
        self.current = now

    def now(self):
        return self.current


class InMemorySeatMutations:
    def __init__(self):
        self.seats = {
            ("flight-204", "1A"): SeatAllocation(
                "flight-204", "1A", SeatStatus.AVAILABLE, FlightStatus.ON_TIME
            ),
            ("flight-204", "1B"): SeatAllocation(
                "flight-204", "1B", SeatStatus.AVAILABLE, FlightStatus.ON_TIME
            ),
        }

    async def mutate(self, flight_id, seat_number, transition):
        key = (flight_id, seat_number)
        seat = self.seats.get(key)
        if seat is None:
            return None
        updated = transition(seat)
        self.seats[key] = updated
        return updated


def test_hold_confirm_and_release_keep_each_flight_seat_independent():
    repository = InMemorySeatMutations()
    clock = FixedClock(NOW)

    async def run():
        held = await HoldSeat(repository, clock).execute("flight-204", "1A", "res-1", EXPIRY)
        assert held.status is SeatStatus.HELD
        assert await HoldSeat(repository, clock).execute(
            "flight-204", "1A", "res-1", EXPIRY
        ) == held
        booked = await ConfirmSeat(repository, clock).execute("flight-204", "1A", "res-1")
        assert booked.status is SeatStatus.BOOKED
        assert await ConfirmSeat(repository, clock).execute("flight-204", "1A", "res-1") == booked
        released = await ReleaseSeat(repository).execute("flight-204", "1A", "res-1")
        assert released.status is SeatStatus.AVAILABLE
        assert repository.seats[("flight-204", "1B")].status is SeatStatus.AVAILABLE

    asyncio.run(run())


def test_conflicting_reservations_cannot_take_or_release_an_active_hold():
    repository = InMemorySeatMutations()
    clock = FixedClock(NOW)

    async def run():
        await HoldSeat(repository, clock).execute("flight-204", "1A", "res-1", EXPIRY)
        with pytest.raises(SeatConflict):
            await HoldSeat(repository, clock).execute("flight-204", "1A", "res-2", EXPIRY)
        with pytest.raises(SeatConflict):
            await ReleaseSeat(repository).execute("flight-204", "1A", "res-2")
        assert repository.seats[("flight-204", "1A")].reservation_id == "res-1"

    asyncio.run(run())


def test_expiry_and_confirmation_at_same_deadline_cannot_both_win():
    repository = InMemorySeatMutations()
    clock = FixedClock(NOW)

    async def run():
        await HoldSeat(repository, clock).execute("flight-204", "1A", "res-1", EXPIRY)
        clock.current = EXPIRY
        with pytest.raises(HoldExpired):
            await ConfirmSeat(repository, clock).execute("flight-204", "1A", "res-1")
        expired = await ExpireSeat(repository, clock).execute("flight-204", "1A")
        assert expired.status is SeatStatus.AVAILABLE
        with pytest.raises(SeatConflict):
            await ConfirmSeat(repository, clock).execute("flight-204", "1A", "res-1")

    asyncio.run(run())


def test_missing_flight_or_seat_is_explicit():
    async def run():
        with pytest.raises(SeatNotFound):
            await HoldSeat(InMemorySeatMutations(), FixedClock(NOW)).execute(
                "missing", "1A", "res-1", EXPIRY
            )

    asyncio.run(run())
