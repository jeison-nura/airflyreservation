"""Inventory commands; no HTTP, SQL, or reservation orchestration here."""

from collections.abc import Callable
from datetime import datetime

from flight_booking.modules.inventory.application.ports import (
    Clock,
    CommandContext,
    SeatMutationRepository,
)
from flight_booking.modules.inventory.domain.seat_allocation import SeatAllocation


class SeatNotFound(Exception):
    """The flight/seat identity does not exist in Inventory."""


class _SeatCommand:
    def __init__(self, repository: SeatMutationRepository) -> None:
        self._repository = repository

    async def _change(
        self,
        flight_id: str,
        seat_number: str,
        transition: Callable[[SeatAllocation], SeatAllocation],
        context: CommandContext | None = None,
    ) -> SeatAllocation:
        if context is None:
            result = await self._repository.mutate(flight_id, seat_number, transition)
        else:
            result = await self._repository.mutate(
                flight_id, seat_number, transition, context=context
            )
        if result is None:
            raise SeatNotFound("Flight seat not found")
        return result


class HoldSeat(_SeatCommand):
    def __init__(self, repository: SeatMutationRepository, clock: Clock) -> None:
        super().__init__(repository)
        self._clock = clock

    async def execute(
        self,
        flight_id: str,
        seat_number: str,
        reservation_id: str,
        expires_at: datetime,
        *,
        context: CommandContext | None = None,
    ) -> SeatAllocation:
        return await self._change(
            flight_id,
            seat_number,
            lambda seat: seat.hold(reservation_id, expires_at, self._clock.now()),
            context,
        )


class ConfirmSeat(_SeatCommand):
    def __init__(self, repository: SeatMutationRepository, clock: Clock) -> None:
        super().__init__(repository)
        self._clock = clock

    async def execute(
        self,
        flight_id: str,
        seat_number: str,
        reservation_id: str,
        *,
        context: CommandContext | None = None,
    ) -> SeatAllocation:
        return await self._change(
            flight_id,
            seat_number,
            lambda seat: seat.confirm(reservation_id, self._clock.now()),
            context,
        )


class ReleaseSeat(_SeatCommand):
    async def execute(
        self,
        flight_id: str,
        seat_number: str,
        reservation_id: str,
        *,
        context: CommandContext | None = None,
    ) -> SeatAllocation:
        return await self._change(
            flight_id, seat_number, lambda seat: seat.release(reservation_id), context
        )


class ExpireSeat(_SeatCommand):
    def __init__(self, repository: SeatMutationRepository, clock: Clock) -> None:
        super().__init__(repository)
        self._clock = clock

    async def execute(
        self,
        flight_id: str,
        seat_number: str,
        *,
        context: CommandContext | None = None,
    ) -> SeatAllocation:
        return await self._change(
            flight_id, seat_number, lambda seat: seat.expire(self._clock.now()), context
        )
