import asyncio
from datetime import UTC, datetime, timedelta

from flight_booking.modules.inventory.application.expire_due_holds import ExpireDueHolds
from flight_booking.modules.inventory.domain.models import FlightStatus, SeatStatus
from flight_booking.modules.inventory.domain.seat_allocation import SeatAllocation

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)


class FixedClock:
    def now(self):
        return NOW


class DueSeats:
    async def find_due(self, now, limit):
        assert now == NOW
        assert limit == 10
        # The candidate list can be stale by the time the seat is locked for mutation.
        return [("flight-204", "1A"), ("flight-204", "1B"), ("flight-204", "1C")]


class InMemoryMutations:
    def __init__(self):
        self.seats = {
            ("flight-204", "1A"): SeatAllocation(
                "flight-204",
                "1A",
                SeatStatus.HELD,
                FlightStatus.ON_TIME,
                "reservation-1",
                NOW,
            ),
            ("flight-204", "1B"): SeatAllocation(
                "flight-204",
                "1B",
                SeatStatus.HELD,
                FlightStatus.ON_TIME,
                "reservation-2",
                NOW + timedelta(minutes=5),
            ),
            ("flight-204", "1C"): SeatAllocation(
                "flight-204",
                "1C",
                SeatStatus.BOOKED,
                FlightStatus.ON_TIME,
                "reservation-confirmed",
            ),
        }

    async def mutate(self, flight_id, seat_number, transition):
        key = (flight_id, seat_number)
        self.seats[key] = transition(self.seats[key])
        return self.seats[key]


def test_expire_due_holds_only_counts_transitions_and_is_safe_to_repeat():
    async def exercise():
        repository = InMemoryMutations()
        worker = ExpireDueHolds(DueSeats(), repository, FixedClock())

        assert await worker.run_once(limit=10) == 1
        assert await worker.run_once(limit=10) == 0
        assert repository.seats[("flight-204", "1A")].status is SeatStatus.AVAILABLE
        assert repository.seats[("flight-204", "1B")].status is SeatStatus.HELD
        confirmed = repository.seats[("flight-204", "1C")]
        assert confirmed.status is SeatStatus.BOOKED
        assert confirmed.reservation_id == "reservation-confirmed"

    asyncio.run(exercise())
