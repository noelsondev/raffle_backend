
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class WinnerCreate(BaseModel):
    ticket_number: int = Field(ge=1)
    prize_description: str | None = Field(
        default=None,
        max_length=250,
    )


class DrawCreate(BaseModel):
    drawn_at: datetime
    evidence_url: HttpUrl | None = None
    notes: str | None = None
    winners: list[WinnerCreate] = Field(
        min_length=1,
        max_length=100,
    )


class WinnerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    ticket_number: int
    winner_name: str
    prize_description: str | None
    position: int


class DrawResponse(BaseModel):
    id: int
    raffle_id: int
    evidence_url: str | None
    notes: str | None
    status: str
    drawn_at: datetime
    published_at: datetime | None
    winners: list[WinnerResponse]
