from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PaymentAttemptRecord(Base):
    __tablename__ = "payment_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('AUTHORIZED', 'DENIED', 'CAPTURED', 'VOIDED', 'REFUNDED')",
            name="ck_payment_attempts_status",
        ),
        CheckConstraint("amount > 0", name="ck_payment_attempts_amount"),
        {"schema": "payments"},
    )

    payment_attempt_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    reservation_id: Mapped[str] = mapped_column(String(64), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(16))
    authorize_key: Mapped[str] = mapped_column(String(128), unique=True)
    capture_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    void_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    refund_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
