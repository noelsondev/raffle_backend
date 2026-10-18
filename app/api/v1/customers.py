
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
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
    name = data.name.strip()
    phone = data.phone.strip()

    if len(name) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El nombre debe tener al menos 2 caracteres.",
        )

    if len(phone) < 7 or len(phone) > 25:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Introduce un número de celular válido.",
        )

    # 1. Buscar si ya existe un cliente con ese número.
    customer = db.scalar(
        select(Customer)
        .where(Customer.phone == phone)
        .order_by(Customer.id.asc())
    )

    if customer is not None:
        # 2. Reutilizar el cliente existente.
        return customer

    # 3. Si no existe, crear el cliente.
    customer = Customer(
        name=name,
        phone=phone,
    )

    db.add(customer)
    db.commit()
    db.refresh(customer)

    return customer
