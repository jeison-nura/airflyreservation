from datetime import date
from decimal import Decimal
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from flight_booking.modules.inventory.domain.models import Flight


class AirportResponse(BaseModel):
    code: str
    city: str
    time: str


class FlightResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)

    id: str
    airline: str
    flight_number: str = Field(alias="flightNumber")
    origin: AirportResponse
    destination: AirportResponse
    departure_date: date = Field(alias="departureDate")
    duration: str
    price: Decimal
    currency: str
    available_seats: int = Field(alias="availableSeats")
    status: str

    @field_serializer("price", when_used="json")
    def serialize_price(self, price: Decimal) -> int | float:
        if price == price.to_integral_value():
            return int(price)
        return float(price)


class FlightSearchResponse(BaseModel):
    data: list[FlightResponse]
    pagination: "PaginationResponse"


class PaginationResponse(BaseModel):
    page: int
    page_size: int = Field(alias="pageSize")
    total_items: int = Field(alias="totalItems")
    total_pages: int = Field(alias="totalPages")


class FlightSeatResponse(BaseModel):
    seat_number: str = Field(alias="seatNumber")
    status: str


class FlightSeatsResponse(BaseModel):
    flight_id: str = Field(alias="flightId")
    seats: list[FlightSeatResponse]


def serialize_flight(flight: Flight) -> dict[str, object]:
    return {
        "id": flight.id,
        "airline": flight.airline,
        "flight_number": flight.flight_number,
        "origin": {
            "code": flight.origin.code,
            "city": flight.origin.city,
            "time": flight.origin.time.strftime("%H:%M"),
        },
        "destination": {
            "code": flight.destination.code,
            "city": flight.destination.city,
            "time": flight.destination.time.strftime("%H:%M"),
        },
        "departure_date": flight.departure_date,
        "duration": flight.duration,
        "price": flight.price,
        "currency": flight.currency,
        "available_seats": flight.available_seats,
        "status": flight.status.value,
    }
