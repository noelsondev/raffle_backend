
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.core.database import get_db
from app.models import Admin, Raffle, Ticket, TicketStatus
from app.schemas.ticket import (
    TicketAvailabilityResponse,
    TicketResponse,
)

router = APIRouter(
    prefix="/tickets",
    tags=["Tickets"],
)


@router.get(
    "/raffle/{raffle_id}/availability",
    response_model=TicketAvailabilityResponse,
)
def get_ticket_availability(
    raffle_id: int,
    db: Session = Depends(get_db),
):
    raffle = db.get(Raffle, raffle_id)

    if raffle is None:
        raise HTTPException(
            status_code=404,
            detail="Rifa no encontrada.",
        )

    assigned = db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.raffle_id == raffle_id,
            Ticket.status == TicketStatus.ASSIGNED,
        )
    ) or 0

    available = max(raffle.total_tickets - assigned, 0)
    sold_percentage = round(
        (assigned / raffle.total_tickets) * 100, 2
    ) if raffle.total_tickets > 0 else 0.0

    return TicketAvailabilityResponse(
        raffle_id=raffle.id,
        total_tickets=raffle.total_tickets,
        assigned_tickets=assigned,
        available_tickets=available,
        sold_percentage=sold_percentage,
    )



@router.get(
    "/raffle/{raffle_id}",
    response_model=list[TicketResponse],
)
def list_raffle_tickets(
    raffle_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    number: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    raffle = db.get(Raffle, raffle_id)

    if raffle is None:
        raise HTTPException(
            status_code=404,
            detail="Rifa no encontrada.",
        )

    statement = select(Ticket).where(
        Ticket.raffle_id == raffle_id
    )

    # Si se proporciona un número, buscar ese boleto exacto.
    if number is not None:
        statement = statement.where(Ticket.number == number)

    statement = (
        statement
        .order_by(Ticket.number.asc())
        .offset(skip)
        .limit(limit)
    )

    return list(db.scalars(statement).all())

