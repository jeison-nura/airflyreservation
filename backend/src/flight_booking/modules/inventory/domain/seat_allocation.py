"""Pure Inventory rules for the seat belonging to one flight."""

from dataclasses import dataclass, replace
from datetime import datetime

from flight_booking.modules.inventory.domain.models import FlightStatus, SeatStatus


class SeatConflict(Exception):
    """The requested transition is not allowed for this seat or owner."""


class HoldExpired(SeatConflict):
    """A hold cannot be confirmed at or after its expiry."""


def _require_instant(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamps must include a timezone")


def _require_reservation_id(reservation_id: str) -> None:
    if not reservation_id or not reservation_id.strip() or len(reservation_id) > 64:
        raise ValueError("A reservation ID of at most 64 characters is required")


@dataclass(frozen=True)
class SeatAllocation:
    flight_id: str
    seat_number: str
    status: SeatStatus
    flight_status: FlightStatus
    reservation_id: str | None = None
    hold_expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.flight_id or len(self.flight_id) > 64:
            raise ValueError("A flight ID of at most 64 characters is required")
        if not self.seat_number or len(self.seat_number) > 8:
            raise ValueError("A seat number of at most 8 characters is required")
        if self.status is SeatStatus.HELD:
            if self.reservation_id is None or self.hold_expires_at is None:
                raise ValueError("A held seat requires an owner and an expiry")
            _require_reservation_id(self.reservation_id)
            _require_instant(self.hold_expires_at)
        elif self.status is SeatStatus.BOOKED:
            if self.reservation_id is None or self.hold_expires_at is not None:
                raise ValueError("A booked seat requires an owner but no expiry")
            _require_reservation_id(self.reservation_id)
        elif self.reservation_id is not None or self.hold_expires_at is not None:
            raise ValueError("A free or unavailable seat cannot retain a hold")

    def hold(
        self, reservation_id: str, expires_at: datetime, now: datetime
    ) -> "SeatAllocation":
        _require_reservation_id(reservation_id)
        _require_instant(now)
        _require_instant(expires_at)
        if expires_at <= now:
            raise ValueError("Hold expiry must be after the current time")
        if self.flight_status is FlightStatus.CANCELLED:
            raise SeatConflict("Cannot hold a seat on a cancelled flight")
        if (
            self.status is SeatStatus.HELD
            and self.hold_expires_at is not None
            and self.hold_expires_at > now
        ):
            if self.reservation_id == reservation_id and self.hold_expires_at == expires_at:
                return self
            raise SeatConflict("Seat already held")
        if self.status not in (SeatStatus.AVAILABLE, SeatStatus.HELD):
            raise SeatConflict("Seat is not available")
        # An expired hold can be replaced within the same atomic repository operation.
        return replace(
            self,
            status=SeatStatus.HELD,
            reservation_id=reservation_id,
            hold_expires_at=expires_at,
        )

    def confirm(self, reservation_id: str, now: datetime) -> "SeatAllocation":
        _require_reservation_id(reservation_id)
        _require_instant(now)
        if self.status is SeatStatus.BOOKED and self.reservation_id == reservation_id:
            return self
        if self.status is not SeatStatus.HELD or self.reservation_id != reservation_id:
            raise SeatConflict("Reservation does not own an active hold")
        if self.flight_status is FlightStatus.CANCELLED:
            raise SeatConflict("Cannot confirm a seat on a cancelled flight")
        if self.hold_expires_at is None or self.hold_expires_at <= now:
            raise HoldExpired("Hold has expired")
        return replace(self, status=SeatStatus.BOOKED, hold_expires_at=None)

    def release(self, reservation_id: str) -> "SeatAllocation":
        _require_reservation_id(reservation_id)
        if self.status is SeatStatus.AVAILABLE:
            return self
        if self.status not in (SeatStatus.HELD, SeatStatus.BOOKED):
            raise SeatConflict("Seat cannot be released")
        if self.reservation_id != reservation_id:
            raise SeatConflict("Reservation does not own this seat")
        return replace(
            self, status=SeatStatus.AVAILABLE, reservation_id=None, hold_expires_at=None
        )

    def expire(self, now: datetime) -> "SeatAllocation":
        _require_instant(now)
        if (
            self.status is SeatStatus.HELD
            and self.hold_expires_at is not None
            and self.hold_expires_at <= now
        ):
            return replace(
                self,
                status=SeatStatus.AVAILABLE,
                reservation_id=None,
                hold_expires_at=None,
            )
        return self
