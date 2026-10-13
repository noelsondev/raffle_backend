
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PurchaseCreate(BaseModel):
    customer_id: int = Field(gt=0)
    raffle_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=100)


class PurchaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    raffle_id: int
    quantity: int
    unit_price: Decimal
    total_amount: Decimal
    payment_reference: str
    status: str
    created_at: datetime
