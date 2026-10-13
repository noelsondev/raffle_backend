
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PurchaseStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAYMENT_SUBMITTED = "PAYMENT_SUBMITTED"
    PAID = "PAID"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class Purchase(Base):
    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"),
        nullable=False,
        index=True,
    )

    raffle_id: Mapped[int] = mapped_column(
        ForeignKey("raffles.id"),
        nullable=False,
        index=True,
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    payment_reference: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        unique=True,
        default=lambda: secrets.token_hex(8).upper(),
    )

    status: Mapped[PurchaseStatus] = mapped_column(
        SAEnum(PurchaseStatus, name="purchase_status"),
        nullable=False,
        default=PurchaseStatus.PENDING_PAYMENT,
        server_default=PurchaseStatus.PENDING_PAYMENT.value,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
