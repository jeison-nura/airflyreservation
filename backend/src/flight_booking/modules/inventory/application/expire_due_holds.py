"""One bounded expiry batch; the process scheduler is an outer adapter."""

from flight_booking.modules.inventory.application.ports import (
    Clock,
    ExpiredSeatRepository,
    SeatMutationRepository,
)
from flight_booking.modules.inventory.domain.seat_allocation import SeatAllocation


class ExpireDueHolds:
    def __init__(
        self,
        candidates: ExpiredSeatRepository,
        mutations: SeatMutationRepository,
        clock: Clock,
    ) -> None:
        self._candidates = candidates
        self._mutations = mutations
        self._clock = clock

    async def run_once(self, *, limit: int) -> int:
        due = await self._candidates.find_due(self._clock.now(), limit)
        count = 0
        for flight_id, seat_number in due:
            expired = False

            def transition(seat: SeatAllocation) -> SeatAllocation:
                nonlocal expired
                result = seat.expire(self._clock.now())
                expired = result != seat
                return result

            await self._mutations.mutate(flight_id, seat_number, transition)
            count += expired
        return count
