from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class PaymentStatus(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    DENIED = "DENIED"
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"
    REFUNDED = "REFUNDED"


class PaymentConflict(Exception):
    """The requested operation conflicts with the current payment state."""


@dataclass(frozen=True)
class PaymentAttempt:
    payment_attempt_ref: str
    reservation_id: str
    amount: Decimal
    currency: str
    status: PaymentStatus
