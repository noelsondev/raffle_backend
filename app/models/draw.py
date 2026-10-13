
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RaffleDraw(Base):
    __tablename__ = "raffle_draws"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    raffle_id: Mapped[int] = mapped_column(
        ForeignKey("raffles.id"),
        nullable=False,
        unique=True,
        index=True,
    )

    evidence_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="DRAFT",
    )

    recorded_by: Mapped[int] = mapped_column(
        ForeignKey("admins.id"),
        nullable=False,
    )

    drawn_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class RaffleWinner(Base):
    __tablename__ = "raffle_winners"

    __table_args__ = (
        UniqueConstraint(
            "draw_id",
            "ticket_id",
            name="uq_draw_winner_ticket",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    draw_id: Mapped[int] = mapped_column(
        ForeignKey("raffle_draws.id"),
        nullable=False,
        index=True,
    )

    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id"),
        nullable=False,
    )

    ticket_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    winner_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    prize_description: Mapped[str | None] = mapped_column(
        String(250),
        nullable=True,
    )

    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
