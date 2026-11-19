from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from enum import StrEnum


class FlightStatus(StrEnum):
    ON_TIME = "ON_TIME"
    DELAYED = "DELAYED"
    CANCELLED = "CANCELLED"


class SeatStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    BOOKED = "BOOKED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class FlightSeat:
    flight_id: str
    seat_number: str
    status: SeatStatus


@dataclass(frozen=True)
class Airport:
    code: str
    city: str
    time: time


@dataclass(frozen=True)
class Flight:
    id: str
    airline: str
    flight_number: str
    origin: Airport
    destination: Airport
    departure_date: date
    duration: str
    price: Decimal
    currency: str
    available_seats: int
    status: FlightStatus
