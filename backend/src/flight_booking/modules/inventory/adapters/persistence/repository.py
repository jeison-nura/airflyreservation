from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from flight_booking.modules.inventory.adapters.persistence.models import (
    AirlineRecord,
    AirportRecord,
    CityRecord,
    CommandIdempotencyRecord,
    CurrencyRecord,
    FlightRecord,
    FlightSeatRecord,
    OutboxEventRecord,
)
from flight_booking.modules.inventory.application.ports import (
    CommandContext,
    FlightPrice,
    FlightPriceRepository,
    FlightSearchRepository,
    FlightSearchResult,
    FlightSeatRepository,
    IdempotencyKeyConflict,
    SeatMutationRepository,
)
from flight_booking.modules.inventory.domain.models import (
    Airport,
    Flight,
    FlightSeat,
    FlightStatus,
    SeatStatus,
)
from flight_booking.modules.inventory.domain.seat_allocation import (
    SeatAllocation,
    SeatConflict,
)
from flight_booking.shared.observability import log_event


class SqlAlchemyFlightRepository(FlightSearchRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: date,
        page: int,
        page_size: int,
    ) -> FlightSearchResult:
        origin_airport = aliased(AirportRecord)
        origin_city = aliased(CityRecord)
        destination_airport = aliased(AirportRecord)
        destination_city = aliased(CityRecord)
        available_seats = (
            select(func.count(FlightSeatRecord.seat_number))
            .where(
                FlightSeatRecord.flight_id == FlightRecord.id,
                FlightSeatRecord.status == "AVAILABLE",
            )
            .correlate(FlightRecord)
            .scalar_subquery()
        )
        filters = (
            FlightRecord.origin_airport_code == origin,
            FlightRecord.destination_airport_code == destination,
            FlightRecord.departure_date == departure_date,
        )
        total_items = await self._session.scalar(
            select(func.count(FlightRecord.id)).where(*filters)
        )
        statement = (
            select(
                FlightRecord,
                AirlineRecord.name,
                origin_airport.iata_code,
                origin_city.name,
                FlightRecord.origin_time,
                destination_airport.iata_code,
                destination_city.name,
                FlightRecord.destination_time,
                CurrencyRecord.minor_unit,
                available_seats,
            )
            .join(AirlineRecord, FlightRecord.airline_id == AirlineRecord.id)
            .join(origin_airport, FlightRecord.origin_airport_code == origin_airport.iata_code)
            .join(origin_city, origin_airport.city_id == origin_city.id)
            .join(
                destination_airport,
                FlightRecord.destination_airport_code == destination_airport.iata_code,
            )
            .join(destination_city, destination_airport.city_id == destination_city.id)
            .join(CurrencyRecord, FlightRecord.currency_code == CurrencyRecord.code)
            .where(*filters)
            .order_by(FlightRecord.origin_time, FlightRecord.id)
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        rows = (await self._session.execute(statement)).all()
        flights = [
            Flight(
                id=record.id,
                airline=airline_name,
                flight_number=record.flight_number,
                origin=Airport(origin_code, origin_city_name, origin_time),
                destination=Airport(
                    destination_code,
                    destination_city_name,
                    destination_time,
                ),
                departure_date=record.departure_date,
                duration=f"{record.duration_minutes} min",
                price=Decimal(record.price_minor_units).scaleb(-minor_unit),
                currency=record.currency_code,
                available_seats=available_seats_count,
                status=FlightStatus(record.status),
            )
            for (
                record,
                airline_name,
                origin_code,
                origin_city_name,
                origin_time,
                destination_code,
                destination_city_name,
                destination_time,
                minor_unit,
                available_seats_count,
            ) in rows
        ]
        return FlightSearchResult(flights=flights, total_items=total_items or 0)


class SqlAlchemyFlightPriceRepository(FlightPriceRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_price(self, flight_id: str) -> FlightPrice | None:
        row = (
            await self._session.execute(
                select(
                    FlightRecord.price_minor_units,
                    FlightRecord.currency_code,
                    CurrencyRecord.minor_unit,
                    FlightRecord.status,
                )
                .join(CurrencyRecord, FlightRecord.currency_code == CurrencyRecord.code)
                .where(FlightRecord.id == flight_id)
            )
        ).one_or_none()
        if row is None or row.status == FlightStatus.CANCELLED.value:
            return None
        minor_units, currency, minor_unit, _flight_status = row
        return FlightPrice(
            amount=Decimal(minor_units).scaleb(-minor_unit),
            currency=currency,
        )


class SqlAlchemyFlightSeatRepository(FlightSeatRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_flight(self, flight_id: str) -> Sequence[FlightSeat] | None:
        if await self._session.get(FlightRecord, flight_id) is None:
            return None
        rows = (
            await self._session.scalars(
                select(FlightSeatRecord)
                .where(FlightSeatRecord.flight_id == flight_id)
                .order_by(FlightSeatRecord.seat_number)
            )
        ).all()
        return [
            FlightSeat(row.flight_id, row.seat_number, SeatStatus(row.status))
            for row in rows
        ]


class SqlAlchemySeatMutationRepository(SeatMutationRepository):
    """One transaction per command; PostgreSQL locks flight then seat."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def mutate(
        self,
        flight_id: str,
        seat_number: str,
        transition: Callable[[SeatAllocation], SeatAllocation],
        *,
        context: CommandContext | None = None,
    ) -> SeatAllocation | None:
        async with self._session_factory() as session, session.begin():
            ledger = await self._claim_key(session, context) if context else None
            if ledger is not None and ledger.outcome is not None:
                outcome = ledger.outcome
            else:
                outcome = await self._apply(
                    session, flight_id, seat_number, transition, context
                )
                if ledger is not None:
                    ledger.outcome = outcome
        log_event(
            "inventory", "seat_command",
            correlation_id=context.correlation_id if context else None,
            level="INFO" if outcome["kind"] == "success" else "WARNING",
            operation=context.operation if context else "expire",
            outcome=outcome["kind"],
            status=outcome.get("status"),
        )
        return self._decode(outcome)

    @staticmethod
    async def _claim_key(
        session: AsyncSession, context: CommandContext
    ) -> CommandIdempotencyRecord:
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            insert = postgres_insert(CommandIdempotencyRecord)
        elif dialect == "sqlite":
            insert = sqlite_insert(CommandIdempotencyRecord)
        else:
            raise RuntimeError("Unsupported Inventory database dialect")
        await session.execute(
            insert.values(
                operation=context.operation,
                key=context.key,
                request_hash=context.request_hash,
                outcome=None,
                created_at=datetime.now(UTC),
            ).on_conflict_do_nothing(index_elements=["operation", "key"])
        )
        ledger = await session.get(
            CommandIdempotencyRecord,
            (context.operation, context.key),
            with_for_update=True,
        )
        if ledger is None:
            raise RuntimeError("Idempotency row was not found after insert")
        if ledger.request_hash != context.request_hash:
            raise IdempotencyKeyConflict("Idempotency key used with another request")
        return ledger

    @staticmethod
    async def _apply(
        session: AsyncSession,
        flight_id: str,
        seat_number: str,
        transition: Callable[[SeatAllocation], SeatAllocation],
        context: CommandContext | None,
    ) -> dict[str, Any]:
        flight = await session.scalar(
            select(FlightRecord).where(FlightRecord.id == flight_id).with_for_update(read=True)
        )
        if flight is None:
            return {"kind": "not_found"}
        record = await session.scalar(
            select(FlightSeatRecord)
            .where(
                FlightSeatRecord.flight_id == flight_id,
                FlightSeatRecord.seat_number == seat_number,
            )
            .with_for_update()
        )
        if record is None:
            return {"kind": "not_found"}
        expiry = record.hold_expires_at
        if expiry is not None and expiry.tzinfo is None and session.get_bind().dialect.name == "sqlite":
            expiry = expiry.replace(tzinfo=UTC)
        current = SeatAllocation(
            flight_id=flight_id,
            seat_number=seat_number,
            status=SeatStatus(record.status),
            flight_status=FlightStatus(flight.status),
            reservation_id=record.held_for_reservation_id,
            hold_expires_at=expiry,
        )
        try:
            changed = transition(current)
        except SeatConflict as exc:
            return {"kind": "conflict", "detail": str(exc)}
        except ValueError as exc:
            return {"kind": "invalid", "detail": str(exc)}
        if changed.flight_id != flight_id or changed.seat_number != seat_number:
            raise ValueError("Transition cannot change seat identity")
        if changed != current:
            record.status = changed.status.value
            record.held_for_reservation_id = changed.reservation_id
            record.hold_expires_at = (
                changed.hold_expires_at.astimezone(UTC)
                if changed.hold_expires_at is not None else None
            )
            SqlAlchemySeatMutationRepository._enqueue_events(session, current, changed, context)
        return {
            "kind": "success",
            "flight_id": changed.flight_id,
            "seat_number": changed.seat_number,
            "status": changed.status.value,
            "flight_status": changed.flight_status.value,
            "reservation_id": changed.reservation_id,
            "hold_expires_at": (
                changed.hold_expires_at.isoformat() if changed.hold_expires_at else None
            ),
        }

    @staticmethod
    def _enqueue_events(
        session: AsyncSession,
        before: SeatAllocation,
        after: SeatAllocation,
        context: CommandContext | None,
    ) -> None:
        correlation_id = context.correlation_id if context else uuid4().hex
        causation_id = context.causation_id if context else correlation_id
        events: list[tuple[str, str, str | None, datetime | None, str | None]] = []
        if before.status is SeatStatus.HELD and after.status is SeatStatus.HELD:
            events.append(
                (
                    "SeatHoldReplaced", "HELD", after.reservation_id,
                    after.hold_expires_at, before.reservation_id,
                )
            )
        elif after.status is SeatStatus.HELD:
            events.append(
                ("SeatHeld", "HELD", after.reservation_id, after.hold_expires_at, None)
            )
        elif after.status is SeatStatus.BOOKED:
            events.append(("SeatBooked", "BOOKED", after.reservation_id, None, None))
        elif after.status is SeatStatus.AVAILABLE:
            event_type = (
                "SeatHoldExpired"
                if context is None or context.operation == "expire"
                else "SeatReleased"
            )
            events.append((event_type, "AVAILABLE", before.reservation_id, None, None))
        for event_type, status, reservation_id, expires_at, previous_reservation_id in events:
            session.add(
                OutboxEventRecord(
                    id=uuid4().hex,
                    source="inventory",
                    event_type=event_type,
                    schema_version=1,
                    flight_id=after.flight_id,
                    seat_number=after.seat_number,
                    payload={
                        "flightId": after.flight_id,
                        "seatNumber": after.seat_number,
                        "status": status,
                        "reservationId": reservation_id,
                        "holdExpiresAt": expires_at.isoformat() if expires_at else None,
                        "previousReservationId": previous_reservation_id,
                    },
                    occurred_at=datetime.now(UTC),
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                    attempts=0,
                )
            )

    @staticmethod
    def _decode(outcome: dict[str, Any]) -> SeatAllocation | None:
        kind = outcome["kind"]
        if kind == "not_found":
            return None
        if kind == "conflict":
            raise SeatConflict(outcome["detail"])
        if kind == "invalid":
            raise ValueError(outcome["detail"])
        if kind != "success":
            raise RuntimeError("Unknown Inventory command result")
        return SeatAllocation(
            flight_id=outcome["flight_id"],
            seat_number=outcome["seat_number"],
            status=SeatStatus(outcome["status"]),
            flight_status=FlightStatus(outcome["flight_status"]),
            reservation_id=outcome["reservation_id"],
            hold_expires_at=(
                datetime.fromisoformat(outcome["hold_expires_at"])
                if outcome["hold_expires_at"] else None
            ),
        )
