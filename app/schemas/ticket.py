
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.ticket import TicketStatus


class TicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    raffle_id: int
    purchase_id: int
    customer_id: int
    number: int
    status: TicketStatus
    created_at: datetime


class TicketAvailabilityResponse(BaseModel):
    raffle_id: int
    total_tickets: int
    assigned_tickets: int
    available_tickets: int
    sold_percentage: float
