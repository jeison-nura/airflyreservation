"""Read the current sellable price through Inventory's own repository."""

from flight_booking.modules.inventory.application.ports import (
    FlightPrice,
    FlightPriceRepository,
)


class GetFlightPrice:
    def __init__(self, repository: FlightPriceRepository) -> None:
        self._repository = repository

    async def execute(self, flight_id: str) -> FlightPrice | None:
        return await self._repository.get_price(flight_id)
