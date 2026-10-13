
import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.core.database import get_db
from app.models.admin import Admin
from app.models.customer import Customer
from app.models.payment import Payment, PaymentStatus
from app.models.purchase import Purchase, PurchaseStatus
from app.models.raffle import Raffle, RaffleStatus
from app.models.ticket import Ticket, TicketStatus
from app.schemas.purchase import PurchaseCreate, PurchaseResponse
from app.services.audit import log_admin_action


router = APIRouter(prefix="/purchases", tags=["Purchases"])


@router.post(
    "",
    response_model=PurchaseResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_purchase(
    data: PurchaseCreate,
    db: Session = Depends(get_db),
) -> Purchase:
    customer = db.get(Customer, data.customer_id)

    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cliente no encontrado.",
        )

    # Bloquear la rifa para coordinar las compras concurrentes.
    raffle = (
        db.query(Raffle)
        .filter(Raffle.id == data.raffle_id)
        .with_for_update()
        .first()
    )

    if raffle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rifa no encontrada.",
        )

    if raffle.status != RaffleStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La rifa no está activa.",
        )

    # Contar los boletos que ya existen en la base de datos.
    # Los boletos cancelados también ocupan su número debido
    # a la restricción única de raffle_id y number.
    existing_ticket_count = (
        db.query(func.count(Ticket.id))
        .filter(Ticket.raffle_id == raffle.id)
        .scalar()
    ) or 0

    # Las compras pendientes reservan disponibilidad.
    # Las compras PAID no se suman aquí porque sus boletos
    # ya se contabilizan en la tabla Ticket.
    pending_reserved_count = (
        db.query(
            func.coalesce(func.sum(Purchase.quantity), 0)
        )
        .filter(
            Purchase.raffle_id == raffle.id,
            Purchase.status.in_(
                [
                    PurchaseStatus.PENDING_PAYMENT,
                    PurchaseStatus.PAYMENT_SUBMITTED,
                ]
            ),
        )
        .scalar()
    ) or 0

    available_count = (
        raffle.total_tickets
        - existing_ticket_count
        - pending_reserved_count
    )

    if available_count < data.quantity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No hay suficientes boletos disponibles para esta compra.",
        )

    unit_price = raffle.price
    total_amount = unit_price * data.quantity

    purchase = Purchase(
        customer_id=customer.id,
        raffle_id=raffle.id,
        quantity=data.quantity,
        unit_price=unit_price,
        total_amount=total_amount,
        status=PurchaseStatus.PENDING_PAYMENT,
    )

    try:
        db.add(purchase)
        db.commit()
        db.refresh(purchase)

    except Exception as exc:
        db.rollback()
        logging.exception("Error registrando una compra.")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo registrar la compra.",
        ) from exc

    return purchase


@router.get("/by-reference/{reference}")
def get_purchase_by_reference(
    reference: str,
    db: Session = Depends(get_db),
):
    reference = reference.strip().upper()

    # Las referencias generadas por el sistema tienen 16 caracteres
    # hexadecimales.
    if len(reference) != 16 or any(
        character not in "0123456789ABCDEF"
        for character in reference
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La referencia de compra no tiene un formato válido.",
        )

    purchase = (
        db.query(Purchase)
        .filter(Purchase.payment_reference == reference)
        .first()
    )

    if purchase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró una compra con esa referencia.",
        )

    raffle = db.get(Raffle, purchase.raffle_id)

    payment = (
        db.query(Payment)
        .filter(Payment.purchase_id == purchase.id)
        .first()
    )

    ticket_rows = (
        db.query(Ticket.number)
        .filter(
            Ticket.purchase_id == purchase.id,
            Ticket.status == TicketStatus.ASSIGNED,
        )
        .order_by(Ticket.number.asc())
        .all()
    )

    ticket_numbers = [number for (number,) in ticket_rows]

    return {
        "reference": purchase.payment_reference,
        "raffle": raffle.title if raffle else None,
        "purchase_status": purchase.status.value,
        "payment_status": payment.status.value if payment else None,
        "quantity_purchased": purchase.quantity,
        "quantity_assigned": len(ticket_numbers),
        "total_amount": str(purchase.total_amount),
        "ticket_numbers": ticket_numbers,
        "tickets_pending_assignment": (
            purchase.status == PurchaseStatus.PAID
            and len(ticket_numbers) != purchase.quantity
        ),
    }


@router.post("/repair-purchase/{purchase_id}/tickets")
def repair_paid_purchase_tickets(
    purchase_id: int,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    assigned_numbers = []

    try:
        purchase = (
            db.query(Purchase)
            .filter(Purchase.id == purchase_id)
            .with_for_update()
            .first()
        )

        if purchase is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Compra no encontrada.",
            )

        if purchase.status != PurchaseStatus.PAID:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La compra no está pagada.",
            )

        payment = (
            db.query(Payment)
            .filter(Payment.purchase_id == purchase.id)
            .with_for_update()
            .first()
        )

        if (
            payment is None
            or payment.status != PaymentStatus.VERIFIED
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El pago no está verificado.",
            )

        existing_tickets = (
            db.query(Ticket)
            .filter(Ticket.purchase_id == purchase.id)
            .all()
        )

        if len(existing_tickets) >= purchase.quantity:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Esta compra ya tiene todos sus boletos.",
            )

        if any(
            ticket.status == TicketStatus.CANCELLED
            for ticket in existing_tickets
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "La compra contiene boletos cancelados; "
                    "requiere revisión manual."
                ),
            )

        raffle = (
            db.query(Raffle)
            .filter(Raffle.id == purchase.raffle_id)
            .with_for_update()
            .first()
        )

        if raffle is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rifa no encontrada.",
            )

        if raffle.status in {
            RaffleStatus.FINISHED,
            RaffleStatus.CANCELLED,
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La rifa está finalizada o cancelada.",
            )

        existing_numbers = {
            number
            for (number,) in (
                db.query(Ticket.number)
                .filter(Ticket.raffle_id == raffle.id)
                .all()
            )
        }

        missing_quantity = (
            purchase.quantity - len(existing_tickets)
        )

        available_numbers = [
            number
            for number in range(1, raffle.total_tickets + 1)
            if number not in existing_numbers
        ]

        if len(available_numbers) < missing_quantity:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No hay suficientes boletos disponibles.",
            )

        assigned_numbers = secrets.SystemRandom().sample(
            available_numbers,
            k=missing_quantity,
        )

        for number in assigned_numbers:
            db.add(
                Ticket(
                    raffle_id=raffle.id,
                    purchase_id=purchase.id,
                    customer_id=purchase.customer_id,
                    number=number,
                    status=TicketStatus.ASSIGNED,
                )
            )

        db.flush()

        log_admin_action(
            db=db,
            admin_id=current_admin.id,
            action="PURCHASE_TICKETS_REPAIRED",
            entity_type="purchase",
            entity_id=purchase.id,
            details={
                "raffle_id": raffle.id,
                "customer_id": purchase.customer_id,
                "assigned_ticket_numbers": sorted(assigned_numbers),
                "quantity_repaired": len(assigned_numbers),
            },
        )

        db.commit()

        return {
            "message": "Boletos reparados correctamente.",
            "purchase_id": purchase.id,
            "quantity_repaired": len(assigned_numbers),
            "assigned_ticket_numbers": sorted(assigned_numbers),
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as exc:
        db.rollback()

        logging.exception(
            "Error reparando los boletos de la compra %s",
            purchase_id,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al reparar los boletos.",
        ) from exc


@router.patch("/{purchase_id}/cancel")
def cancel_purchase(
    purchase_id: int,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    try:
        purchase = (
            db.query(Purchase)
            .filter(Purchase.id == purchase_id)
            .with_for_update()
            .first()
        )

        if purchase is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Compra no encontrada.",
            )

        if purchase.status != PurchaseStatus.PENDING_PAYMENT:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Solo se pueden cancelar compras "
                    "pendientes de pago sin comprobante."
                ),
            )

        existing_payment = (
            db.query(Payment)
            .filter(Payment.purchase_id == purchase.id)
            .first()
        )

        if existing_payment is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "La compra tiene un pago registrado. "
                    "Debe revisarse antes de cancelarla."
                ),
            )

        purchase.status = PurchaseStatus.CANCELLED

        log_admin_action(
            db=db,
            admin_id=current_admin.id,
            action="PURCHASE_CANCELLED",
            entity_type="purchase",
            entity_id=purchase.id,
            details={
                "raffle_id": purchase.raffle_id,
                "customer_id": purchase.customer_id,
                "quantity": purchase.quantity,
                "reason": "Cancelación administrativa",
            },
        )

        db.commit()
        db.refresh(purchase)

        return {
            "message": "Compra cancelada correctamente.",
            "purchase_id": purchase.id,
            "purchase_status": purchase.status.value,
            "released_quantity": purchase.quantity,
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as exc:
        db.rollback()

        logging.exception(
            "Error cancelando la compra %s.",
            purchase_id,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo cancelar la compra.",
        ) from exc
