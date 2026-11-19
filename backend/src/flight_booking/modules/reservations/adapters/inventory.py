"""In-process adapter from Reservations commands to Inventory's application port."""

import hashlib
import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flight_booking.modules.inventory.adapters.clock import SystemClock
from flight_booking.modules.inventory.adapters.persistence.repository import (
    SqlAlchemyFlightPriceRepository,
    SqlAlchemySeatMutationRepository,
)
from flight_booking.modules.inventory.adapters.persistence.session import SessionFactory
from flight_booking.modules.inventory.application.get_flight_price import (
    GetFlightPrice,
)
from flight_booking.modules.inventory.application.manage_seats import (
    ConfirmSeat,
    HoldSeat,
    ReleaseSeat,
    SeatNotFound,
)
from flight_booking.modules.inventory.application.ports import CommandContext
from flight_booking.modules.inventory.domain.seat_allocation import SeatConflict
from flight_booking.modules.reservations.application.create_reservation import (
    SeatDoesNotExist,
    SeatUnavailable,
)
from flight_booking.modules.reservations.application.ports import FlightQuote


class InventoryCommandsAdapter:
    """Call Inventory use cases directly; never access its tables from Reservations."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession] = SessionFactory
    ) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _context(
        operation: str,
        flight_id: str,
        seat_number: str,
        reservation_id: str,
        *,
        correlation_id: str,
        expires_at: datetime | None = None,
    ) -> CommandContext:
        request = {
            "flightId": flight_id,
            "seatNumber": seat_number,
            "reservationId": reservation_id,
            "expiresAt": expires_at.isoformat() if expires_at else None,
        }
        return CommandContext(
            operation=operation,
            key=f"reservation-{reservation_id}-{operation}",
            request_hash=hashlib.sha256(
                json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            correlation_id=correlation_id,
            causation_id=uuid4().hex,
        )

    async def hold(
        self,
        flight_id: str,
        seat_number: str,
        reservation_id: str,
        expires_at: datetime,
        *,
        correlation_id: str,
    ) -> None:
        context = self._context(
            "hold",
            flight_id,
            seat_number,
            reservation_id,
            correlation_id=correlation_id,
            expires_at=expires_at,
        )
        try:
            await HoldSeat(
                SqlAlchemySeatMutationRepository(self._session_factory), SystemClock()
            ).execute(
                flight_id,
                seat_number,
                reservation_id,
                expires_at,
                context=context,
            )
        except SeatNotFound as exc:
            raise SeatDoesNotExist from exc
        except SeatConflict as exc:
            raise SeatUnavailable from exc


    async def confirm(
        self,
        flight_id: str,
        seat_number: str,
        reservation_id: str,
        *,
        correlation_id: str,
    ) -> None:
        try:
            await ConfirmSeat(
                SqlAlchemySeatMutationRepository(self._session_factory), SystemClock()
            ).execute(
                flight_id,
                seat_number,
                reservation_id,
                context=self._context(
                    "confirm",
                    flight_id,
                    seat_number,
                    reservation_id,
                    correlation_id=correlation_id,
                ),
            )
        except SeatNotFound as exc:
            raise SeatDoesNotExist from exc
        except SeatConflict as exc:
            raise SeatUnavailable from exc


    async def release(
        self,
        flight_id: str,
        seat_number: str,
        reservation_id: str,
        *,
        correlation_id: str,
    ) -> None:
        try:
            await ReleaseSeat(
                SqlAlchemySeatMutationRepository(self._session_factory)
            ).execute(
                flight_id,
                seat_number,
                reservation_id,
                context=self._context(
                    "release",
                    flight_id,
                    seat_number,
                    reservation_id,
                    correlation_id=correlation_id,
                ),
            )
        except SeatNotFound as exc:
            raise SeatDoesNotExist from exc
        except SeatConflict as exc:
            raise SeatUnavailable from exc


class InventoryFlightPricingAdapter:
    """Obtain price by invoking Inventory's query use case and repository."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession] = SessionFactory
    ) -> None:
        self._session_factory = session_factory

    async def quote(self, flight_id: str) -> FlightQuote | None:
        async with self._session_factory() as session:
            price = await GetFlightPrice(
                SqlAlchemyFlightPriceRepository(session)
            ).execute(flight_id)
        if price is None:
            return None
        return FlightQuote(price.amount, price.currency)
