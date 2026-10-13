
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.raffle import RaffleStatus


class RaffleCreate(BaseModel):
    title: str = Field(min_length=3, max_length=150)
    description: str | None = None
    price: Decimal = Field(gt=0, decimal_places=2)
    total_tickets: int = Field(ge=1, le=1_000_000)
    minimum_tickets: int = Field(default=2, ge=1)
    start_at: datetime | None = None
    end_at: datetime | None = None


class RaffleUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=150)
    description: str | None = None
    price: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    minimum_tickets: int | None = Field(default=None, ge=1)
    start_at: datetime | None = None
    end_at: datetime | None = None


class RaffleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    image_path: str | None = None
    price: Decimal
    total_tickets: int
    minimum_tickets: int
    status: RaffleStatus
    start_at: datetime | None
    end_at: datetime | None
    created_at: datetime
    updated_at: datetime

class PublicRaffleResponse(RaffleResponse):
    sold_tickets: int = 0
    sold_percentage: float = 0.0
    remaining_percentage: float = 100.0


class RaffleStatusUpdate(BaseModel):
    status: RaffleStatus
