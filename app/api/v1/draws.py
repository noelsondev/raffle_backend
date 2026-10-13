
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.core.database import get_db
from app.models import (
    Admin,
    Customer,
    Payment,
    PaymentStatus,
    Purchase,
    PurchaseStatus,
    Raffle,
    RaffleDraw,
    RaffleStatus,
    RaffleWinner,
    Ticket,
    TicketStatus,
)
from app.schemas.draw import DrawCreate, DrawResponse
from app.services.audit import log_admin_action

router = APIRouter(prefix="/draws", tags=["Draws"])


@router.post(
    "/raffle/{raffle_id}",
    response_model=DrawResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_draw(
    raffle_id: int,
    data: DrawCreate,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    try:
        # Bloquear la rifa para evitar registros simultáneos.
        raffle = db.scalar(
            select(Raffle)
            .where(Raffle.id == raffle_id)
            .with_for_update()
        )

        if raffle is None:
            raise HTTPException(
                status_code=404,
                detail="Rifa no encontrada.",
            )

        if raffle.status != RaffleStatus.ACTIVE:
            raise HTTPException(
                status_code=409,
                detail="Solo se puede registrar el resultado de una rifa activa.",
            )

        existing_draw = db.scalar(
            select(RaffleDraw).where(
                RaffleDraw.raffle_id == raffle_id
            )
        )

        if existing_draw is not None:
            raise HTTPException(
                status_code=409,
                detail="Esta rifa ya tiene un resultado registrado.",
            )

        if data.drawn_at > datetime.now(timezone.utc):
            raise HTTPException(
                status_code=400,
                detail="La fecha del sorteo no puede estar en el futuro.",
            )

        ticket_numbers = [
            winner.ticket_number for winner in data.winners
        ]

        if len(ticket_numbers) != len(set(ticket_numbers)):
            raise HTTPException(
                status_code=400,
                detail="No se puede repetir un número de boleto.",
            )

        draw = RaffleDraw(
            raffle_id=raffle.id,
            evidence_url=(
                str(data.evidence_url)
                if data.evidence_url else None
            ),
            notes=data.notes,
            status="DRAFT",
            recorded_by=current_admin.id,
            drawn_at=data.drawn_at,
        )

        db.add(draw)
        db.flush()

        for position, winner_data in enumerate(data.winners, start=1):
            ticket = db.scalar(
                select(Ticket).where(
                    Ticket.raffle_id == raffle_id,
                    Ticket.number == winner_data.ticket_number,
                    Ticket.status == TicketStatus.ASSIGNED,
                )
            )

            if ticket is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"El boleto {winner_data.ticket_number} "
                        "no existe o no está asignado a esta rifa."
                    ),
                )

            purchase = db.scalar(
                select(Purchase).where(
                    Purchase.id == ticket.purchase_id,
                    Purchase.raffle_id == raffle_id,
                    Purchase.status == PurchaseStatus.PAID,
                )
            )

            if purchase is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"El boleto {winner_data.ticket_number} "
                        "no pertenece a una compra pagada."
                    ),
                )

            payment = db.scalar(
                select(Payment).where(
                    Payment.purchase_id == purchase.id,
                    Payment.status == PaymentStatus.VERIFIED,
                )
            )

            if payment is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"El pago del boleto "
                        f"{winner_data.ticket_number} no está verificado."
                    ),
                )

            customer = db.get(Customer, ticket.customer_id)

            if customer is None:
                raise HTTPException(
                    status_code=400,
                    detail="No se encontró el participante del boleto.",
                )

            db.add(
                RaffleWinner(
                    draw_id=draw.id,
                    ticket_id=ticket.id,
                    ticket_number=ticket.number,
                    winner_name=customer.name,
                    prize_description=winner_data.prize_description,
                    position=position,
                )
            )

        
        db.flush()

        # Registrar la creación del resultado como borrador.
        log_admin_action(
            db=db,
            admin_id=current_admin.id,
            action="DRAW_REGISTERED",
            entity_type="draw",
            entity_id=draw.id,
            details={
                "raffle_id": raffle.id,
                "draw_status": draw.status,
                "drawn_at": draw.drawn_at.isoformat(),
                "winner_ticket_numbers": ticket_numbers,
                "winners_count": len(ticket_numbers),
                "evidence_url": draw.evidence_url,
            },
        )

        # Guardar el resultado y su auditoría juntos.
        db.commit()


        saved_draw = db.scalar(
            select(RaffleDraw).where(
                RaffleDraw.id == draw.id
            )
        )

        winners = list(
            db.scalars(
                select(RaffleWinner)
                .where(RaffleWinner.draw_id == draw.id)
                .order_by(RaffleWinner.position)
            ).all()
        )

        return DrawResponse(
            id=saved_draw.id,
            raffle_id=saved_draw.raffle_id,
            evidence_url=saved_draw.evidence_url,
            notes=saved_draw.notes,
            status=saved_draw.status,
            drawn_at=saved_draw.drawn_at,
            published_at=saved_draw.published_at,
            winners=winners,
        )

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="No se pudo registrar el resultado del sorteo.",
        )


@router.patch(
    "/raffle/{raffle_id}/publish",
    response_model=DrawResponse,
)
def publish_draw(
    raffle_id: int,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    try:
        # Bloquear la rifa para evitar publicaciones simultáneas.
        raffle = db.scalar(
            select(Raffle)
            .where(Raffle.id == raffle_id)
            .with_for_update()
        )

        if raffle is None:
            raise HTTPException(
                status_code=404,
                detail="Rifa no encontrada.",
            )

        draw = db.scalar(
            select(RaffleDraw)
            .where(RaffleDraw.raffle_id == raffle_id)
            .with_for_update()
        )

        if draw is None:
            raise HTTPException(
                status_code=404,
                detail="No hay un resultado registrado para esta rifa.",
            )

        if draw.status != "DRAFT":
            raise HTTPException(
                status_code=409,
                detail="El resultado ya fue publicado o no está en borrador.",
            )

        winners = list(
            db.scalars(
                select(RaffleWinner)
                .where(RaffleWinner.draw_id == draw.id)
                .order_by(RaffleWinner.position)
            ).all()
        )

        if not winners:
            raise HTTPException(
                status_code=400,
                detail="No se puede publicar sin ganadores.",
            )

        # Volver a validar los boletos antes de publicar.
        for winner in winners:
            ticket = db.get(Ticket, winner.ticket_id)

            if (
                ticket is None
                or ticket.raffle_id != raffle_id
                or ticket.number != winner.ticket_number
                or ticket.status != TicketStatus.ASSIGNED
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Uno de los boletos ganadores ya no es válido.",
                )

            purchase = db.scalar(
                select(Purchase).where(
                    Purchase.id == ticket.purchase_id,
                    Purchase.raffle_id == raffle_id,
                    Purchase.status == PurchaseStatus.PAID,
                )
            )

            if purchase is None:
                raise HTTPException(
                    status_code=409,
                    detail="La compra de un boleto ganador no está pagada.",
                )

            payment = db.scalar(
                select(Payment).where(
                    Payment.purchase_id == purchase.id,
                    Payment.status == PaymentStatus.VERIFIED,
                )
            )

            if payment is None:
                raise HTTPException(
                    status_code=409,
                    detail="El pago de un boleto ganador no está verificado.",
                )

        
        old_raffle_status = raffle.status.value

        draw.status = "PUBLISHED"
        draw.published_at = datetime.now(timezone.utc)
        raffle.status = RaffleStatus.FINISHED

        log_admin_action(
            db=db,
            admin_id=current_admin.id,
            action="DRAW_PUBLISHED",
            entity_type="draw",
            entity_id=draw.id,
            details={
                "raffle_id": raffle.id,
                "raffle_title": raffle.title,
                "draw_status": draw.status,
                "old_raffle_status": old_raffle_status,
                "new_raffle_status": raffle.status.value,
                "winner_ticket_numbers": [
                    winner.ticket_number for winner in winners
                ],
                "winners_count": len(winners),
                "published_at": draw.published_at.isoformat(),
            },
        )

        # Guardar publicación, estado de la rifa y auditoría juntos.
        db.commit()


        db.refresh(draw)

        winners = list(
            db.scalars(
                select(RaffleWinner)
                .where(RaffleWinner.draw_id == draw.id)
                .order_by(RaffleWinner.position)
            ).all()
        )

        return DrawResponse(
            id=draw.id,
            raffle_id=draw.raffle_id,
            evidence_url=draw.evidence_url,
            notes=draw.notes,
            status=draw.status,
            drawn_at=draw.drawn_at,
            published_at=draw.published_at,
            winners=winners,
        )

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="No se pudo publicar el resultado del sorteo.",
        )



@router.get(
    "/raffle/{raffle_id}/results",
    response_model=DrawResponse,
)
def get_public_draw_result(
    raffle_id: int,
    db: Session = Depends(get_db),
):
    draw = db.scalar(
        select(RaffleDraw).where(
            RaffleDraw.raffle_id == raffle_id,
            RaffleDraw.status == "PUBLISHED",
        )
    )

    if draw is None:
        raise HTTPException(
            status_code=404,
            detail="Esta rifa todavía no tiene resultados publicados.",
        )

    winners = list(
        db.scalars(
            select(RaffleWinner)
            .where(RaffleWinner.draw_id == draw.id)
            .order_by(RaffleWinner.position)
        ).all()
    )

    return DrawResponse(
        id=draw.id,
        raffle_id=draw.raffle_id,
        evidence_url=draw.evidence_url,
        notes=draw.notes,
        status=draw.status,
        drawn_at=draw.drawn_at,
        published_at=draw.published_at,
        winners=winners,
    )


@router.get("/results")
def get_public_draw_history(
    db: Session = Depends(get_db),
):
    draws = list(
        db.scalars(
            select(RaffleDraw)
            .where(RaffleDraw.status == "PUBLISHED")
            .order_by(RaffleDraw.published_at.desc())
        ).all()
    )

    results = []

    for draw in draws:
        raffle = db.get(Raffle, draw.raffle_id)

        if raffle is None:
            continue

        winners = list(
            db.scalars(
                select(RaffleWinner)
                .where(RaffleWinner.draw_id == draw.id)
                .order_by(RaffleWinner.position)
            ).all()
        )

        results.append({
            "raffle_id": raffle.id,
            "raffle_title": raffle.title,
            "raffle_status": raffle.status.value,
            "drawn_at": draw.drawn_at,
            "published_at": draw.published_at,
            "evidence_url": draw.evidence_url,
            "winners": [
                {
                    "name": winner.winner_name,
                    "ticket_number": winner.ticket_number,
                    "prize_description": winner.prize_description,
                    "position": winner.position,
                }
                for winner in winners
            ],
        })

    return results
