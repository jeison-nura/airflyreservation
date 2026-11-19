from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from flight_booking.modules.inventory.domain.models import Flight, FlightSeat
from flight_booking.modules.inventory.domain.seat_allocation import SeatAllocation


@dataclass(frozen=True)
class FlightSearchResult:
    flights: Sequence[Flight]
    total_items: int


class FlightSearchRepository(Protocol):
    async def search(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: date,
        page: int,
        page_size: int,
    ) -> FlightSearchResult: ...


class FlightSeatRepository(Protocol):
    async def get_by_flight(self, flight_id: str) -> Sequence[FlightSeat] | None: ...


@dataclass(frozen=True)
class FlightPrice:
    amount: Decimal
    currency: str


class FlightPriceRepository(Protocol):
    async def get_price(self, flight_id: str) -> FlightPrice | None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True)
class CommandContext:
    operation: str
    key: str
    request_hash: str
    correlation_id: str
    causation_id: str


class IdempotencyKeyConflict(Exception):
    """The key was already used for another request in this operation."""


class SeatMutationRepository(Protocol):
    async def mutate(
        self,
        flight_id: str,
        seat_number: str,
        transition: Callable[[SeatAllocation], SeatAllocation],
        *,
        context: CommandContext | None = None,
    ) -> SeatAllocation | None:
        """Atomically load the seat and flight status, apply transition, persist and commit.

        Lock the flight against status changes (shared lock) and then the seat
        row exclusively before invoking transition; roll back on any exception.
        Return None if the seat does not exist.
        """
        ...


class ExpiredSeatRepository(Protocol):
    async def find_due(self, now: datetime, limit: int) -> Sequence[tuple[str, str]]: ...
