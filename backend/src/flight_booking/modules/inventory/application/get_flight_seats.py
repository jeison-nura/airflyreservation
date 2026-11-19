from collections.abc import Sequence

from flight_booking.modules.inventory.application.ports import FlightSeatRepository
from flight_booking.modules.inventory.domain.models import FlightSeat


class GetFlightSeats:
    def __init__(self, repository: FlightSeatRepository) -> None:
        self._repository = repository

    async def execute(self, flight_id: str) -> Sequence[FlightSeat] | None:
        return await self._repository.get_by_flight(flight_id)
