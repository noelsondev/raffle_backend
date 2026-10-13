
from pydantic import BaseModel, Field


class PaymentReview(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    reason: str | None = Field(default=None, max_length=500)
