"""Public Reservations HTTP schemas."""

import re
from datetime import datetime
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class PassengerInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    full_name: str = Field(alias="fullName", min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("email must be a valid email address")
        return value


class CreateReservationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    flight_id: str = Field(alias="flightId", min_length=1, max_length=64)
    seat_number: str = Field(alias="seatNumber", min_length=1, max_length=8)
    passenger: PassengerInput


class ReservationCreatedResponse(BaseModel):
    reservation_id: str = Field(alias="reservationId")
    status: str
    flight_id: str = Field(alias="flightId")
    seat_number: str = Field(alias="seatNumber")
    expires_at: AwareDatetime = Field(alias="expiresAt")
    amount: Decimal | None = None
    currency: str | None = None
    access_token: str | None = Field(default=None, alias="accessToken")
    correlation_id: str | None = Field(default=None, alias="correlationId")
    replayed: bool = False
    access_credential_available: bool = Field(
        default=True, alias="accessCredentialAvailable"
    )

    model_config = ConfigDict(populate_by_name=True)


class ReservationStatusResponse(BaseModel):
    reservation_id: str = Field(alias="reservationId")
    status: str
    flight_id: str = Field(alias="flightId")
    seat_number: str = Field(alias="seatNumber")
    expires_at: datetime = Field(alias="expiresAt")
    amount: Decimal | None = None
    currency: str | None = None
    booking_code: str | None = Field(alias="bookingCode")
    failure_reason: str | None = Field(alias="failureReason")
    sequence: int

    model_config = ConfigDict(populate_by_name=True)


class ReservationNotificationResponse(BaseModel):
    notification_id: str = Field(alias="notificationId")
    sequence: int
    status: str
    occurred_at: AwareDatetime = Field(alias="occurredAt")

    model_config = ConfigDict(populate_by_name=True)


class ReservationNotificationsResponse(BaseModel):
    events: list[ReservationNotificationResponse]
