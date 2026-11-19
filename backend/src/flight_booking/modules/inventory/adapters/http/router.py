from datetime import date
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy.ext.asyncio import AsyncSession

from flight_booking.modules.inventory.adapters.http.schemas import (
    FlightResponse,
    FlightSearchResponse,
    FlightSeatResponse,
    FlightSeatsResponse,
    PaginationResponse,
    serialize_flight,
)
from flight_booking.modules.inventory.adapters.http.seat_commands import (
    router as seat_commands_router,
)
from flight_booking.modules.inventory.adapters.persistence.repository import (
    SqlAlchemyFlightRepository,
    SqlAlchemyFlightSeatRepository,
)
from flight_booking.modules.inventory.adapters.persistence.session import (
    SessionFactory,
    get_session,
)
from flight_booking.modules.inventory.application.get_flight_seats import GetFlightSeats
from flight_booking.modules.inventory.application.search_flights import SearchFlights
from flight_booking.shared.realtime import (
    WS_ALLOWED_ORIGINS,
    flight_seat_connections,
)

router = APIRouter()
router.include_router(seat_commands_router)


async def get_search_flights(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SearchFlights:
    return SearchFlights(SqlAlchemyFlightRepository(session))


async def get_flight_seats(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GetFlightSeats:
    return GetFlightSeats(SqlAlchemyFlightSeatRepository(session))


@router.get("/flights", response_model=FlightSearchResponse)
async def search_flights(
    origin: Annotated[str, Query(min_length=3, max_length=3, pattern="^[A-Za-z]{3}$")],
    destination: Annotated[str, Query(min_length=3, max_length=3, pattern="^[A-Za-z]{3}$")],
    departure_date: Annotated[date, Query(alias="departureDate")],
    use_case: Annotated[SearchFlights, Depends(get_search_flights)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
) -> FlightSearchResponse:
    if origin.upper() == destination.upper():
        raise HTTPException(status_code=422, detail="origin and destination must differ")

    result = await use_case.execute(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        page=page,
        page_size=page_size,
    )
    return FlightSearchResponse(
        data=[
            FlightResponse.model_validate(serialize_flight(flight))
            for flight in result.flights
        ],
        pagination=PaginationResponse(
            page=page,
            pageSize=page_size,
            totalItems=result.total_items,
            totalPages=(result.total_items + page_size - 1) // page_size,
        ),
    )


@router.get("/flights/{flight_id}/seats", response_model=FlightSeatsResponse)
async def read_flight_seats(
    flight_id: Annotated[str, Path(min_length=1, max_length=64)],
    use_case: Annotated[GetFlightSeats, Depends(get_flight_seats)],
) -> FlightSeatsResponse:
    seats = await use_case.execute(flight_id)
    if seats is None:
        raise HTTPException(status_code=404, detail="Flight not found")
    return FlightSeatsResponse(
        flightId=flight_id,
        seats=[
            FlightSeatResponse(seatNumber=seat.seat_number, status=seat.status.value)
            for seat in seats
        ],
    )


@router.websocket("/flights/{flight_id}/events/ws")
async def flight_seat_events(
    websocket: WebSocket,
    flight_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> None:
    if websocket.headers.get("origin") not in WS_ALLOWED_ORIGINS:
        await websocket.close(code=1008)
        return
    async with SessionFactory() as session:
        seats = await GetFlightSeats(
            SqlAlchemyFlightSeatRepository(session)
        ).execute(flight_id)
    if seats is None:
        await websocket.close(code=1008)
        return
    await flight_seat_connections.connect(flight_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        flight_seat_connections.disconnect(flight_id, websocket)
