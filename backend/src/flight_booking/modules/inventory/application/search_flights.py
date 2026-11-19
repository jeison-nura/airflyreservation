from datetime import date

from flight_booking.modules.inventory.application.ports import (
    FlightSearchRepository,
    FlightSearchResult,
)


class SearchFlights:
    def __init__(self, repository: FlightSearchRepository) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: date,
        page: int,
        page_size: int,
    ) -> FlightSearchResult:
        return await self._repository.search(
            origin=origin.upper(),
            destination=destination.upper(),
            departure_date=departure_date,
            page=page,
            page_size=page_size,
        )
