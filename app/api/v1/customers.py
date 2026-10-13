
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.customer import Customer
from app.schemas.customer import CustomerCreate, CustomerResponse

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.post(
    "",
    response_model=CustomerResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_customer(
    data: CustomerCreate,
    db: Session = Depends(get_db),
) -> Customer:
    customer = Customer(
        name=data.name.strip(),
        phone=data.phone.strip(),
    )

    if len(customer.name) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El nombre debe tener al menos 2 caracteres.",
        )

    db.add(customer)
    db.commit()
    db.refresh(customer)

    return customer
