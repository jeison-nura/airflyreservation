"""Internal-only Inventory command controllers."""

import hashlib
import json
import os
from collections.abc import Awaitable
from dataclasses import dataclass
from hmac import compare_digest
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Path
from fastapi.security import APIKeyHeader
from pydantic import AwareDatetime, BaseModel, Field

from flight_booking.modules.inventory.adapters.clock import SystemClock
from flight_booking.modules.inventory.adapters.persistence.repository import (
    SqlAlchemySeatMutationRepository,
)
from flight_booking.modules.inventory.adapters.persistence.session import SessionFactory
from flight_booking.modules.inventory.application.manage_seats import (
    ConfirmSeat,
    ExpireSeat,
    HoldSeat,
    ReleaseSeat,
    SeatNotFound,
)
from flight_booking.modules.inventory.application.ports import (
    Clock,
    CommandContext,
    IdempotencyKeyConflict,
    SeatMutationRepository,
)
from flight_booking.modules.inventory.domain.seat_allocation import (
    SeatAllocation,
    SeatConflict,
)

service_header = APIKeyHeader(name="X-Inventory-Service-Token", auto_error=False)


def require_inventory_token(
    token: Annotated[str | None, Depends(service_header)],
) -> None:
    expected = os.getenv("INVENTORY_INTERNAL_TOKEN")
    if not expected or len(expected) < 24:
        raise HTTPException(status_code=503, detail="Inventory commands not configured")
    if token is None or not compare_digest(token, expected):
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "APIKey"},
        )


def get_seat_clock() -> Clock:
    return SystemClock()


def get_seat_mutations() -> SeatMutationRepository:
    return SqlAlchemySeatMutationRepository(SessionFactory)


class ReservationCommand(BaseModel):
    reservation_id: str = Field(alias="reservationId", min_length=1, max_length=64)


class HoldCommand(ReservationCommand):
    expires_at: AwareDatetime = Field(alias="expiresAt")


class SeatCommandResponse(BaseModel):
    flight_id: str = Field(alias="flightId")
    seat_number: str = Field(alias="seatNumber")
    status: str


FlightId = Annotated[str, Path(min_length=1, max_length=64)]
SeatNumber = Annotated[str, Path(min_length=1, max_length=8)]

router = APIRouter(dependencies=[Depends(require_inventory_token)])


@dataclass(frozen=True)
class CommandHeaders:
    key: str
    correlation_id: str


def get_command_headers(
    key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=128,
            pattern="^[A-Za-z0-9_-]+$",
        ),
    ],
    correlation_id: Annotated[
        str | None,
        Header(alias="X-Correlation-ID", max_length=64, pattern="^[A-Za-z0-9_-]+$"),
    ] = None,
) -> CommandHeaders:
    return CommandHeaders(key, correlation_id or uuid4().hex)


def command_context(
    operation: str,
    flight_id: str,
    seat_number: str,
    body: BaseModel | None,
    headers: CommandHeaders,
) -> CommandContext:
    request = {
        "flightId": flight_id,
        "seatNumber": seat_number,
        "body": body.model_dump(mode="json", by_alias=True) if body else None,
    }
    payload = json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    return CommandContext(
        operation=operation,
        key=headers.key,
        request_hash=hashlib.sha256(payload).hexdigest(),
        correlation_id=headers.correlation_id,
        causation_id=uuid4().hex,
    )


async def _result(operation: Awaitable[SeatAllocation]) -> SeatCommandResponse:
    try:
        seat = await operation
    except SeatNotFound as exc:
        raise HTTPException(status_code=404, detail="Flight seat not found") from exc
    except SeatConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IdempotencyKeyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SeatCommandResponse(
        flightId=seat.flight_id,
        seatNumber=seat.seat_number,
        status=seat.status.value,
    )


@router.post(
    "/flights/{flight_id}/seats/{seat_number}/hold", response_model=SeatCommandResponse
)
async def hold_seat(
    flight_id: FlightId,
    seat_number: SeatNumber,
    body: HoldCommand,
    repository: Annotated[SeatMutationRepository, Depends(get_seat_mutations)],
    clock: Annotated[Clock, Depends(get_seat_clock)],
    headers: Annotated[CommandHeaders, Depends(get_command_headers)],
) -> SeatCommandResponse:
    return await _result(
        HoldSeat(repository, clock).execute(
            flight_id,
            seat_number,
            body.reservation_id,
            body.expires_at,
            context=command_context("hold", flight_id, seat_number, body, headers),
        )
    )


@router.post(
    "/flights/{flight_id}/seats/{seat_number}/confirm",
    response_model=SeatCommandResponse,
)
async def confirm_seat(
    flight_id: FlightId,
    seat_number: SeatNumber,
    body: ReservationCommand,
    repository: Annotated[SeatMutationRepository, Depends(get_seat_mutations)],
    clock: Annotated[Clock, Depends(get_seat_clock)],
    headers: Annotated[CommandHeaders, Depends(get_command_headers)],
) -> SeatCommandResponse:
    return await _result(
        ConfirmSeat(repository, clock).execute(
            flight_id,
            seat_number,
            body.reservation_id,
            context=command_context("confirm", flight_id, seat_number, body, headers),
        )
    )


@router.post(
    "/flights/{flight_id}/seats/{seat_number}/release",
    response_model=SeatCommandResponse,
)
async def release_seat(
    flight_id: FlightId,
    seat_number: SeatNumber,
    body: ReservationCommand,
    repository: Annotated[SeatMutationRepository, Depends(get_seat_mutations)],
    headers: Annotated[CommandHeaders, Depends(get_command_headers)],
) -> SeatCommandResponse:
    return await _result(
        ReleaseSeat(repository).execute(
            flight_id,
            seat_number,
            body.reservation_id,
            context=command_context("release", flight_id, seat_number, body, headers),
        )
    )


@router.post(
    "/flights/{flight_id}/seats/{seat_number}/expire",
    response_model=SeatCommandResponse,
)
async def expire_seat(
    flight_id: FlightId,
    seat_number: SeatNumber,
    repository: Annotated[SeatMutationRepository, Depends(get_seat_mutations)],
    clock: Annotated[Clock, Depends(get_seat_clock)],
    headers: Annotated[CommandHeaders, Depends(get_command_headers)],
) -> SeatCommandResponse:
    return await _result(
        ExpireSeat(repository, clock).execute(
            flight_id,
            seat_number,
            context=command_context("expire", flight_id, seat_number, None, headers),
        )
    )
