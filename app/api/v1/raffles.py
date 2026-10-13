
import io
import logging
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from PIL import Image
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.core.database import get_db
from app.models import (
    Admin,
    Raffle,
    RaffleStatus,
    Purchase,
    PurchaseStatus,
    Ticket,
    TicketStatus,
    Payment,
    PaymentStatus,
)
from app.models.customer import Customer
from app.schemas.raffle import (
    RaffleCreate,
    RaffleResponse,
    PublicRaffleResponse,
    RaffleStatusUpdate,
    RaffleUpdate,
)
from app.services.audit import log_admin_action
from app.services.supabase_storage import (
    upload_raffle_image as upload_image_to_supabase,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/raffles",
    tags=["Raffles"],
)


@router.post(
    "",
    response_model=RaffleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_raffle(
    data: RaffleCreate,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> Raffle:
    raffle = Raffle(
        title=data.title,
        description=data.description,
        price=data.price,
        total_tickets=data.total_tickets,
        minimum_tickets=data.minimum_tickets,
        status=RaffleStatus.DRAFT,
        start_at=data.start_at,
        end_at=data.end_at,
    )

    db.add(raffle)
    db.flush()

    log_admin_action(
        db=db,
        admin_id=current_admin.id,
        action="RAFFLE_CREATED",
        entity_type="raffle",
        entity_id=raffle.id,
        details={
            "title": raffle.title,
            "price": str(raffle.price),
            "total_tickets": raffle.total_tickets,
            "minimum_tickets": raffle.minimum_tickets,
            "initial_status": raffle.status.value,
        },
    )

    db.commit()
    db.refresh(raffle)

    return raffle


@router.get(
    "",
    response_model=list[RaffleResponse],
)
def list_raffles(
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> list[Raffle]:
    return list(
        db.scalars(
            select(Raffle).order_by(Raffle.id.desc())
        ).all()
    )


@router.get(
    "/public/active",
    response_model=list[PublicRaffleResponse],
)
def get_active_public_raffles(
    db: Session = Depends(get_db),
):
    statement = (
        select(Raffle)
        .where(Raffle.status == RaffleStatus.ACTIVE)
        .order_by(Raffle.created_at.desc())
    )

    raffles = db.scalars(statement).all()
    results = []

    for raffle in raffles:
        assigned_statement = select(
            func.count(Ticket.id)
        ).where(
            Ticket.raffle_id == raffle.id,
            Ticket.status == TicketStatus.ASSIGNED,
        )

        sold_tickets = db.scalar(assigned_statement) or 0

        if raffle.total_tickets > 0:
            sold_percentage = round(
                sold_tickets / raffle.total_tickets * 100,
                2,
            )
        else:
            sold_percentage = 0.0

        remaining_percentage = round(
            max(0.0, 100.0 - sold_percentage),
            2,
        )

        results.append(
            {
                "id": raffle.id,
                "title": raffle.title,
                "description": raffle.description,
                "image_path": raffle.image_path,
                "price": raffle.price,
                "total_tickets": raffle.total_tickets,
                "minimum_tickets": raffle.minimum_tickets,
                "status": raffle.status,
                "start_at": raffle.start_at,
                "end_at": raffle.end_at,
                "created_at": raffle.created_at,
                "updated_at": raffle.updated_at,
                "sold_tickets": sold_tickets,
                "sold_percentage": sold_percentage,
                "remaining_percentage": remaining_percentage,
            }
        )

    return results


@router.get(
    "/{raffle_id}",
    response_model=RaffleResponse,
)
def get_raffle(
    raffle_id: int,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> Raffle:
    raffle = db.get(Raffle, raffle_id)

    if raffle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rifa no encontrada.",
        )

    return raffle


@router.put(
    "/{raffle_id}",
    response_model=RaffleResponse,
)
def update_raffle(
    raffle_id: int,
    data: RaffleUpdate,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> Raffle:
    raffle = db.get(Raffle, raffle_id)

    if raffle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rifa no encontrada.",
        )

    update_data = data.model_dump(exclude_unset=True)
    changes = {}

    for field, new_value in update_data.items():
        old_value = getattr(raffle, field)

        if hasattr(old_value, "value"):
            old_value = old_value.value

        if hasattr(new_value, "value"):
            new_value = new_value.value

        if old_value != new_value:
            changes[field] = {
                "old": (
                    str(old_value)
                    if old_value is not None
                    else None
                ),
                "new": (
                    str(new_value)
                    if new_value is not None
                    else None
                ),
            }

        setattr(raffle, field, getattr(data, field))

    if changes:
        db.flush()

        log_admin_action(
            db=db,
            admin_id=current_admin.id,
            action="RAFFLE_UPDATED",
            entity_type="raffle",
            entity_id=raffle.id,
            details={"changes": changes},
        )

    db.commit()
    db.refresh(raffle)

    return raffle


@router.patch(
    "/{raffle_id}/status",
    response_model=RaffleResponse,
)
def update_raffle_status(
    raffle_id: int,
    data: RaffleStatusUpdate,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
) -> Raffle:
    raffle = db.get(Raffle, raffle_id)

    if raffle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rifa no encontrada.",
        )

    current_status = raffle.status
    new_status = data.status

    allowed_transitions = {
        RaffleStatus.DRAFT: {
            RaffleStatus.ACTIVE,
            RaffleStatus.CANCELLED,
        },
        RaffleStatus.ACTIVE: {
            RaffleStatus.PAUSED,
            RaffleStatus.FINISHED,
            RaffleStatus.CANCELLED,
        },
        RaffleStatus.PAUSED: {
            RaffleStatus.ACTIVE,
            RaffleStatus.CANCELLED,
        },
        RaffleStatus.FINISHED: set(),
        RaffleStatus.CANCELLED: set(),
    }

    if new_status == current_status:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La rifa ya tiene ese estado.",
        )

    if new_status not in allowed_transitions[current_status]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"No se puede cambiar la rifa de "
                f"{current_status.value} a {new_status.value}."
            ),
        )

    raffle.status = new_status

    log_admin_action(
        db=db,
        admin_id=current_admin.id,
        action="RAFFLE_STATUS_CHANGED",
        entity_type="raffle",
        entity_id=raffle.id,
        details={
            "old_status": current_status.value,
            "new_status": new_status.value,
        },
    )

    db.commit()
    db.refresh(raffle)

    return raffle


@router.get("/{raffle_id}/summary")
def get_raffle_summary(
    raffle_id: int,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    raffle = db.get(Raffle, raffle_id)

    if raffle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rifa no encontrada.",
        )

    assigned_tickets = db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.raffle_id == raffle_id,
            Ticket.status == TicketStatus.ASSIGNED,
        )
    ) or 0

    available_tickets = max(
        raffle.total_tickets - assigned_tickets,
        0,
    )

    sold_percentage = (
        round(
            assigned_tickets / raffle.total_tickets * 100,
            2,
        )
        if raffle.total_tickets > 0
        else 0.0
    )

    revenue = db.scalar(
        select(
            func.coalesce(func.sum(Purchase.total_amount), 0)
        ).where(
            Purchase.raffle_id == raffle_id,
            Purchase.status == PurchaseStatus.PAID,
        )
    )

    return {
        "raffle_id": raffle.id,
        "title": raffle.title,
        "status": raffle.status.value,
        "ticket_price": str(raffle.price),
        "total_tickets": raffle.total_tickets,
        "assigned_tickets": assigned_tickets,
        "available_tickets": available_tickets,
        "sold_percentage": sold_percentage,
        "revenue": str(revenue),
    }


@router.get("/admin/dashboard", tags=["Admin Dashboard"])
def get_admin_dashboard(
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    raffle_stats = db.execute(
        select(
            func.count(Raffle.id).label("total_raffles"),
            func.sum(
                case(
                    (Raffle.status == RaffleStatus.DRAFT, 1),
                    else_=0,
                )
            ).label("draft_raffles"),
            func.sum(
                case(
                    (Raffle.status == RaffleStatus.ACTIVE, 1),
                    else_=0,
                )
            ).label("active_raffles"),
            func.sum(
                case(
                    (Raffle.status == RaffleStatus.PAUSED, 1),
                    else_=0,
                )
            ).label("paused_raffles"),
            func.sum(
                case(
                    (Raffle.status == RaffleStatus.FINISHED, 1),
                    else_=0,
                )
            ).label("finished_raffles"),
            func.sum(
                case(
                    (Raffle.status == RaffleStatus.CANCELLED, 1),
                    else_=0,
                )
            ).label("cancelled_raffles"),
        )
    ).one()

    assigned_tickets = db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.status == TicketStatus.ASSIGNED
        )
    ) or 0

    pending_payments = db.scalar(
        select(func.count(Payment.id)).where(
            Payment.status == PaymentStatus.PENDING
        )
    ) or 0

    rejected_payments = db.scalar(
        select(func.count(Payment.id)).where(
            Payment.status == PaymentStatus.REJECTED
        )
    ) or 0

    pending_purchases = db.scalar(
        select(func.count(Purchase.id)).where(
            Purchase.status.in_(
                [
                    PurchaseStatus.PENDING_PAYMENT,
                    PurchaseStatus.PAYMENT_SUBMITTED,
                ]
            )
        )
    ) or 0

    revenue = db.scalar(
        select(
            func.coalesce(func.sum(Purchase.total_amount), 0)
        ).where(
            Purchase.status == PurchaseStatus.PAID
        )
    )

    total_customers = db.scalar(
        select(func.count(Customer.id))
    ) or 0

    return {
        "total_raffles": raffle_stats.total_raffles or 0,
        "draft_raffles": raffle_stats.draft_raffles or 0,
        "active_raffles": raffle_stats.active_raffles or 0,
        "paused_raffles": raffle_stats.paused_raffles or 0,
        "finished_raffles": raffle_stats.finished_raffles or 0,
        "cancelled_raffles": raffle_stats.cancelled_raffles or 0,
        "assigned_tickets": assigned_tickets,
        "pending_payments": pending_payments,
        "rejected_payments": rejected_payments,
        "pending_purchases": pending_purchases,
        "total_customers": total_customers,
        "confirmed_revenue": str(revenue),
    }


@router.post("/{raffle_id}/image")
def upload_raffle_image(
    raffle_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    max_file_size = 5 * 1024 * 1024

    allowed_formats = {
        "JPEG": (".jpg", "image/jpeg"),
        "PNG": (".png", "image/png"),
        "WEBP": (".webp", "image/webp"),
    }

    raffle = db.get(Raffle, raffle_id)

    if raffle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rifa no encontrada.",
        )

    content = file.file.read(max_file_size + 1)

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo está vacío.",
        )

    if len(content) > max_file_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="La imagen no puede superar los 5 MB.",
        )

    try:
        with Image.open(io.BytesIO(content)) as image:
            image_format = image.format
            image.verify()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo no es una imagen válida.",
        ) from exc

    if image_format not in allowed_formats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se permiten imágenes JPG, PNG o WEBP.",
        )

    extension, content_type = allowed_formats[image_format]
    safe_filename = f"image{extension}"

    try:
        public_url = upload_image_to_supabase(
            file_bytes=content,
            original_filename=safe_filename,
            content_type=content_type,
        )

        raffle.image_path = public_url

        log_admin_action(
            db=db,
            admin_id=current_admin.id,
            action="RAFFLE_IMAGE_UPDATED",
            entity_type="raffle",
            entity_id=raffle.id,
            details={
                "image_path": public_url,
            },
        )

        db.commit()
        db.refresh(raffle)

    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        db.rollback()

        logger.exception(
            "Error al subir imagen de la rifa a Supabase. "
            "Rifa ID: %s",
            raffle_id,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo subir la imagen a Supabase.",
        ) from exc

    return {
        "message": "Imagen de la rifa actualizada correctamente.",
        "raffle_id": raffle.id,
        "image_path": raffle.image_path,
    }
