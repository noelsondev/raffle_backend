
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.core.database import get_db
from app.models.admin import Admin
from app.models.customer import Customer
from app.models.purchase import Purchase
from app.models.raffle import Raffle
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
            status_code=422,
            detail="El nombre debe tener al menos 2 caracteres.",
        )

    if len(phone) < 7 or len(phone) > 25:
        raise HTTPException(
            status_code=422,
            detail="Introduce un número de celular válido.",
        )

    customer = db.scalar(
        select(Customer)
        .where(Customer.phone == phone)
        .order_by(Customer.id.asc())
    )

    if customer is not None:
        return customer

    customer = Customer(name=name, phone=phone)
    db.add(customer)
    db.commit()
    db.refresh(customer)

    return customer


@router.get("/admin/all")
def list_all_customers(
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    statement = (
        select(
            Customer,
            func.count(Purchase.id).label("purchase_count"),
        )
        .outerjoin(
            Purchase,
            Purchase.customer_id == Customer.id,
        )
        .group_by(Customer.id)
        .order_by(Customer.id.desc())
    )

    rows = db.execute(statement).all()

    return [
        {
            "id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "created_at": customer.created_at,
            "purchase_count": purchase_count,
        }
        for customer, purchase_count in rows
    ]


@router.get("/admin/{customer_id}")
def get_customer_details(
    customer_id: int,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    customer = db.get(Customer, customer_id)

    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró el cliente.",
        )

    statement = (
        select(Purchase, Raffle.title)
        .join(Raffle, Raffle.id == Purchase.raffle_id)
        .where(Purchase.customer_id == customer_id)
        .order_by(Purchase.created_at.desc())
    )

    rows = db.execute(statement).all()

    purchases = [
        {
            "id": purchase.id,
            "raffle_id": purchase.raffle_id,
            "raffle_title": raffle_title,
            "quantity": purchase.quantity,
            "unit_price": purchase.unit_price,
            "total_amount": purchase.total_amount,
            "payment_reference": purchase.payment_reference,
            "status": purchase.status.value,
            "created_at": purchase.created_at,
        }
        for purchase, raffle_title in rows
    ]

    return {
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "created_at": customer.created_at,
        },
        "purchases": purchases,
    }
