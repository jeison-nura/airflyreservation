from datetime import date, datetime, time
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CityRecord(Base):
    __tablename__ = "cities"
    __table_args__ = (
        UniqueConstraint("name", "country_code", name="uq_cities_name_country"),
        {"schema": "inventory"},
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    country_code: Mapped[str] = mapped_column(String(2))


class AirportRecord(Base):
    __tablename__ = "airports"
    __table_args__ = (
        CheckConstraint("length(iata_code) = 3", name="ck_airports_iata_code_length"),
        {"schema": "inventory"},
    )

    iata_code: Mapped[str] = mapped_column(String(3), primary_key=True)
    city_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("inventory.cities.id"),
        index=True,
    )


class AirlineRecord(Base):
    __tablename__ = "airlines"
    __table_args__ = ({"schema": "inventory"},)

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)


class CurrencyRecord(Base):
    __tablename__ = "currencies"
    __table_args__ = (
        CheckConstraint("length(code) = 3", name="ck_currencies_code_length"),
        CheckConstraint("minor_unit BETWEEN 0 AND 4", name="ck_currencies_minor_unit"),
        {"schema": "inventory"},
    )

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    minor_unit: Mapped[int] = mapped_column(SmallInteger)


class FlightRecord(Base):
    __tablename__ = "flights"
    __table_args__ = (
        CheckConstraint(
            "origin_airport_code <> destination_airport_code",
            name="ck_flights_distinct_airports",
        ),
        CheckConstraint("price_minor_units >= 0", name="ck_flights_nonnegative_price"),
        CheckConstraint("duration_minutes >= 0", name="ck_flights_nonnegative_duration"),
        CheckConstraint(
            "status IN ('ON_TIME', 'DELAYED', 'CANCELLED')",
            name="ck_flights_status",
        ),
        Index(
            "ix_flights_route_departure",
            "origin_airport_code",
            "destination_airport_code",
            "departure_date",
        ),
        {"schema": "inventory"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    airline_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("inventory.airlines.id"),
        index=True,
    )
    flight_number: Mapped[str] = mapped_column(String(32))
    origin_airport_code: Mapped[str] = mapped_column(
        String(3),
        ForeignKey("inventory.airports.iata_code"),
    )
    destination_airport_code: Mapped[str] = mapped_column(
        String(3),
        ForeignKey("inventory.airports.iata_code"),
    )
    departure_date: Mapped[date] = mapped_column(Date)
    origin_time: Mapped[time] = mapped_column(Time)
    destination_time: Mapped[time] = mapped_column(Time)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    price_minor_units: Mapped[int] = mapped_column(BigInteger)
    currency_code: Mapped[str] = mapped_column(
        String(3),
        ForeignKey("inventory.currencies.code"),
    )
    status: Mapped[str] = mapped_column(String(16))


class FlightSeatRecord(Base):
    __tablename__ = "flight_seats"
    __table_args__ = (
        Index(
            "ix_inventory_seats_due",
            "status",
            "hold_expires_at",
            "flight_id",
            "seat_number",
        ),
        CheckConstraint(
            "status IN ('AVAILABLE', 'HELD', 'BOOKED', 'UNAVAILABLE')",
            name="ck_flight_seats_status",
        ),
        CheckConstraint(
            "status <> 'HELD' OR hold_expires_at IS NOT NULL",
            name="ck_flight_seats_held_has_expiry",
        ),
        {"schema": "inventory"},
    )

    flight_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("inventory.flights.id", ondelete="CASCADE"),
        primary_key=True,
    )
    seat_number: Mapped[str] = mapped_column(String(8), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    held_for_reservation_id: Mapped[str | None] = mapped_column(String(64))
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CommandIdempotencyRecord(Base):
    __tablename__ = "command_idempotency"
    __table_args__ = ({"schema": "inventory"},)

    operation: Mapped[str] = mapped_column(String(16), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OutboxEventRecord(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_inventory_outbox_pending", "delivered_at", "claim_until", "occurred_at"),
        {"schema": "inventory"},
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    event_type: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[int] = mapped_column(Integer)
    flight_id: Mapped[str] = mapped_column(String(64))
    seat_number: Mapped[str] = mapped_column(String(8))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[str] = mapped_column(String(64))
    causation_id: Mapped[str] = mapped_column(String(64))
    claimed_by: Mapped[str | None] = mapped_column(String(64))
    claim_token: Mapped[str | None] = mapped_column(String(32))
    claim_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
