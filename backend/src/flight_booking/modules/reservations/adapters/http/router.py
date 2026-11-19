import hashlib
from asyncio import wait_for
from hmac import compare_digest
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from flight_booking.modules.inventory.adapters.clock import SystemClock
from flight_booking.modules.payments.adapters.commands import SqlAlchemyPaymentCommands
from flight_booking.modules.reservations.adapters.http.realtime import (
    reservation_connections,
)
from flight_booking.modules.reservations.adapters.http.schemas import (
    CreateReservationRequest,
    ReservationCreatedResponse,
    ReservationNotificationResponse,
    ReservationNotificationsResponse,
    ReservationStatusResponse,
)
from flight_booking.modules.reservations.adapters.inventory import (
    InventoryCommandsAdapter,
    InventoryFlightPricingAdapter,
)
from flight_booking.modules.reservations.adapters.persistence.repository import (
    SqlAlchemyReservationRepository,
)
from flight_booking.modules.reservations.adapters.persistence.session import (
    SessionFactory,
)
from flight_booking.modules.reservations.application.confirm_reservation import (
    ConfirmReservation,
)
from flight_booking.modules.reservations.application.create_reservation import (
    CreateReservation,
    ReservationClock,
    SeatDoesNotExist,
    SeatUnavailable,
)
from flight_booking.modules.reservations.application.ports import (
    IdempotencyKeyConflict,
    PaymentCommands,
    ReservationBookingRepository,
)
from flight_booking.modules.reservations.domain.models import (
    ReservationAggregate,
    ReservationConflict,
)
from flight_booking.shared.realtime import WS_ALLOWED_ORIGINS

router = APIRouter()


def get_reservation_repository() -> ReservationBookingRepository:
    return SqlAlchemyReservationRepository(SessionFactory)


def get_reservation_clock() -> ReservationClock:
    return SystemClock()


def get_create_reservation(
    repository: Annotated[
        ReservationBookingRepository, Depends(get_reservation_repository)
    ],
    clock: Annotated[ReservationClock, Depends(get_reservation_clock)],
) -> CreateReservation:
    return CreateReservation(
        repository,
        InventoryCommandsAdapter(),
        InventoryFlightPricingAdapter(),
        clock,
    )


def get_payment_commands() -> PaymentCommands:
    return SqlAlchemyPaymentCommands()


def get_confirm_reservation(
    repository: Annotated[
        ReservationBookingRepository, Depends(get_reservation_repository)
    ],
    payments: Annotated[PaymentCommands, Depends(get_payment_commands)],
) -> ConfirmReservation:
    return ConfirmReservation(
        repository, InventoryCommandsAdapter(), payments, SystemClock()
    )


def _reservation_response(
    aggregate: ReservationAggregate,
) -> ReservationStatusResponse:
    reservation = aggregate.reservation
    return ReservationStatusResponse(
        reservationId=reservation.id,
        status=reservation.status.value,
        flightId=reservation.flight_id,
        seatNumber=reservation.seat_number,
        expiresAt=reservation.expires_at,
        amount=reservation.amount,
        currency=reservation.currency,
        bookingCode=reservation.booking_code,
        failureReason=reservation.failure_reason,
        sequence=0,
    )


@router.post(
    "",
    response_model=ReservationCreatedResponse,
    response_model_exclude_none=True,
    status_code=201,
)
async def create_reservation(
    body: CreateReservationRequest,
    use_case: Annotated[CreateReservation, Depends(get_create_reservation)],
    http_response: Response,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=128,
            pattern="^[A-Za-z0-9_-]+$",
        ),
    ],
) -> ReservationCreatedResponse:
    try:
        result = await use_case.execute(
            flight_id=body.flight_id,
            seat_number=body.seat_number,
            full_name=body.passenger.full_name,
            email=body.passenger.email,
            idempotency_key=idempotency_key,
        )
    except IdempotencyKeyConflict as exc:
        raise HTTPException(
            status_code=409, detail="IDEMPOTENCY_KEY_REUSED"
        ) from exc
    except SeatUnavailable as exc:
        raise HTTPException(status_code=409, detail="SEAT_UNAVAILABLE") from exc
    except SeatDoesNotExist as exc:
        raise HTTPException(
            status_code=404, detail="FLIGHT_OR_SEAT_NOT_FOUND"
        ) from exc

    reservation = result.aggregate.reservation
    response = ReservationCreatedResponse(
        reservationId=reservation.id,
        status=reservation.status.value,
        flightId=reservation.flight_id,
        seatNumber=reservation.seat_number,
        expiresAt=reservation.expires_at,
        amount=reservation.amount,
        currency=reservation.currency,
        accessToken=result.access_token,
        correlationId=(
            result.aggregate.saga.correlation_id if not result.replayed else None
        ),
        replayed=result.replayed,
        accessCredentialAvailable=not result.replayed,
    )
    if result.replayed:
        # Idempotent replay cannot recover or reissue the original bearer secret.
        http_response.status_code = status.HTTP_200_OK
        return response
    return response


async def _get_authorized_aggregate(
    reservation_id: Annotated[str, Path(min_length=1, max_length=64)],
    repository: ReservationBookingRepository,
    authorization: str | None,
) -> ReservationAggregate:
    aggregate = await repository.get(reservation_id)
    if aggregate is None:
        raise HTTPException(status_code=404, detail="RESERVATION_NOT_FOUND")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="UNAUTHORIZED",
            headers={"WWW-Authenticate": "Bearer"},
        )
    await _validate_access_token(repository, reservation_id, authorization[7:])
    return aggregate


async def _validate_access_token(
    repository: ReservationBookingRepository,
    reservation_id: str,
    token: str,
) -> None:
    stored_hash = await repository.get_access_credential_hash(reservation_id)
    supplied_hash = hashlib.sha256(token.encode()).hexdigest()
    if not token or stored_hash is None or not compare_digest(stored_hash, supplied_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="UNAUTHORIZED",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/{reservation_id}", response_model=ReservationStatusResponse)
async def get_reservation(
    reservation_id: Annotated[str, Path(min_length=1, max_length=64)],
    repository: Annotated[
        ReservationBookingRepository, Depends(get_reservation_repository)
    ],
    authorization: Annotated[str | None, Header()] = None,
) -> ReservationStatusResponse:
    aggregate = await _get_authorized_aggregate(
        reservation_id, repository, authorization
    )
    sequence = await repository.get_notification_sequence(reservation_id)
    return _reservation_response(aggregate).model_copy(update={"sequence": sequence})


@router.post(
    "/{reservation_id}/confirm",
    response_model=ReservationStatusResponse,
)
async def confirm_reservation(
    reservation_id: Annotated[str, Path(min_length=1, max_length=64)],
    use_case: Annotated[
        ConfirmReservation, Depends(get_confirm_reservation)
    ],
    repository: Annotated[
        ReservationBookingRepository, Depends(get_reservation_repository)
    ],
    http_response: Response,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=128,
            pattern="^[A-Za-z0-9_-]+$",
        ),
    ],
    authorization: Annotated[str | None, Header()] = None,
) -> ReservationStatusResponse:
    await _get_authorized_aggregate(reservation_id, repository, authorization)
    try:
        result = await use_case.execute(
            reservation_id, idempotency_key=idempotency_key
        )
    except IdempotencyKeyConflict as exc:
        raise HTTPException(
            status_code=409, detail="IDEMPOTENCY_KEY_REUSED"
        ) from exc
    except ReservationConflict as exc:
        message = str(exc)
        if message == "Reservation expired":
            raise HTTPException(status_code=409, detail="RESERVATION_EXPIRED") from exc
        raise HTTPException(
            status_code=409, detail="RESERVATION_NOT_CONFIRMABLE"
        ) from exc
    http_response.status_code = (
        status.HTTP_202_ACCEPTED if result.pending else status.HTTP_200_OK
    )
    sequence = await repository.get_notification_sequence(reservation_id)
    return _reservation_response(result.aggregate).model_copy(
        update={"sequence": sequence}
    )


@router.get(
    "/{reservation_id}/events",
    response_model=ReservationNotificationsResponse,
)
async def get_reservation_events(
    reservation_id: Annotated[str, Path(min_length=1, max_length=64)],
    repository: Annotated[
        ReservationBookingRepository, Depends(get_reservation_repository)
    ],
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    authorization: Annotated[str | None, Header()] = None,
) -> ReservationNotificationsResponse:
    await _get_authorized_aggregate(reservation_id, repository, authorization)
    events = await repository.get_notifications_after(
        reservation_id, after, limit=limit
    )
    return ReservationNotificationsResponse(
        events=[
            ReservationNotificationResponse(
                notificationId=event.notification_id,
                sequence=event.sequence,
                status=event.status,
                occurredAt=event.occurred_at,
            )
            for event in events
        ]
    )


@router.websocket("/{reservation_id}/events/ws")
async def reservation_events_websocket(
    websocket: WebSocket,
    reservation_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> None:
    origin = websocket.headers.get("origin")
    if origin not in WS_ALLOWED_ORIGINS:
        await websocket.close(code=1008)
        return
    try:
        auth_message = await wait_for(websocket.receive_json(), timeout=5)
    except (TimeoutError, WebSocketDisconnect, ValueError):
        await websocket.close(code=1008)
        return
    if (
        not isinstance(auth_message, dict)
        or auth_message.get("type") != "subscribe"
        or not isinstance(auth_message.get("accessToken"), str)
        or not isinstance(auth_message.get("afterSequence", 0), int)
        or auth_message.get("afterSequence", 0) < 0
    ):
        await websocket.close(code=1008)
        return

    repository = get_reservation_repository()
    aggregate = await repository.get(reservation_id)
    if aggregate is None:
        await websocket.close(code=1008)
        return
    try:
        await _validate_access_token(
            repository, reservation_id, auth_message["accessToken"]
        )
    except HTTPException:
        await websocket.close(code=1008)
        return

    await reservation_connections.connect(reservation_id, websocket)
    try:
        events = await repository.get_notifications_after(
            reservation_id, auth_message.get("afterSequence", 0), limit=500
        )
        for event in events:
            await websocket.send_json(
                {
                    "type": "reservation.updated",
                    "notificationId": event.notification_id,
                    "sequence": event.sequence,
                    "status": event.status,
                    "bookingCode": (
                        aggregate.reservation.booking_code
                        if event.status == "CONFIRMED"
                        else None
                    ),
                    "failureReason": (
                        aggregate.reservation.failure_reason
                        if event.status == "FAILED"
                        else None
                    ),
                }
            )
        while True:
            # Keep the connection alive; client messages are not commands.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        reservation_connections.disconnect(reservation_id, websocket)
