
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TicketStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CANCELLED = "CANCELLED"


class Ticket(Base):
    __tablename__ = "tickets"

    __table_args__ = (
        UniqueConstraint(
            "raffle_id",
            "number",
            name="uq_ticket_raffle_number",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    raffle_id: Mapped[int] = mapped_column(
        ForeignKey("raffles.id"),
        nullable=False,
        index=True,
    )

    purchase_id: Mapped[int] = mapped_column(
        ForeignKey("purchases.id"),
        nullable=False,
        index=True,
    )

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"),
        nullable=False,
        index=True,
    )

    number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    status: Mapped[TicketStatus] = mapped_column(
        SAEnum(TicketStatus, name="ticket_status"),
        nullable=False,
        default=TicketStatus.ASSIGNED,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
