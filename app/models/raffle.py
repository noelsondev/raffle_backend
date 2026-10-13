from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RaffleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"


class Raffle(Base):
    __tablename__ = "raffles"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    title: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    image_path: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    minimum_tickets: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=2,
        server_default="2",
    )

    total_tickets: Mapped[int] = mapped_column(
    Integer,
    nullable=False,
    )

    status: Mapped[RaffleStatus] = mapped_column(
        SAEnum(RaffleStatus, name="raffle_status"),
        nullable=False,
        default=RaffleStatus.DRAFT,
        server_default=RaffleStatus.DRAFT.value,
    )

    start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


 