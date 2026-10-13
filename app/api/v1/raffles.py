from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

import io
import uuid
from pathlib import Path

from fastapi import File, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image

from app.api.dependencies import get_current_admin
from app.core.database import get_db
from app.models import Admin, Raffle, RaffleStatus
from app.schemas.raffle import (
    RaffleCreate,
    RaffleResponse,
    RaffleStatusUpdate,
    RaffleUpdate,
)

from app.models import Purchase, PurchaseStatus, Ticket, TicketStatus,Payment, PaymentStatus
from app.models.customer import Customer
from app.services.audit import log_admin_action


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

    # Registrar la creación de la rifa.
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

    # Guardar la rifa y su auditoría en una sola transacción.
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

    # Guardar los valores anteriores antes de modificarlos.
    changes = {}

    for field, new_value in update_data.items():
        old_value = getattr(raffle, field)

        if hasattr(old_value, "value"):
            old_value = old_value.value

        if hasattr(new_value, "value"):
            new_value = new_value.value

        if old_value != new_value:
            changes[field] = {
                "old": str(old_value) if old_value is not None else None,
                "new": str(new_value) if new_value is not None else None,
            }

        setattr(raffle, field, getattr(data, field))

    # Registrar solo si hubo cambios reales.
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

    # Guardar los cambios y la auditoría juntos.
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

    # Guardar el cambio y la auditoría juntos.
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

    sold_percentage = round(
        assigned_tickets / raffle.total_tickets * 100,
        2,
    ) if raffle.total_tickets > 0 else 0.0

    revenue = db.scalar(
        select(func.coalesce(func.sum(Purchase.total_amount), 0)).where(
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

@router.get("/admin/dashboard", tags=["Admin Dashboard"])
def get_admin_dashboard(
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    # Estadísticas de rifas
    raffle_stats = db.execute(
        select(
            func.count(Raffle.id).label("total_raffles"),
            func.sum(
                case((Raffle.status == RaffleStatus.DRAFT, 1), else_=0)
            ).label("draft_raffles"),
            func.sum(
                case((Raffle.status == RaffleStatus.ACTIVE, 1), else_=0)
            ).label("active_raffles"),
            func.sum(
                case((Raffle.status == RaffleStatus.PAUSED, 1), else_=0)
            ).label("paused_raffles"),
            func.sum(
                case((Raffle.status == RaffleStatus.FINISHED, 1), else_=0)
            ).label("finished_raffles"),
            func.sum(
                case((Raffle.status == RaffleStatus.CANCELLED, 1), else_=0)
            ).label("cancelled_raffles"),
        )
    ).one()

    # Estadísticas de tickets
    assigned_tickets = db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.status == TicketStatus.ASSIGNED
        )
    ) or 0

    # Estadísticas de pagos
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

    # Estadísticas de compras
    pending_purchases = db.scalar(
        select(func.count(Purchase.id)).where(
            Purchase.status.in_([
                PurchaseStatus.PENDING_PAYMENT,
                PurchaseStatus.PAYMENT_SUBMITTED,
            ])
        )
    ) or 0

    # Ingresos de compras pagadas
    revenue = db.scalar(
        select(
            func.coalesce(func.sum(Purchase.total_amount), 0)
        ).where(
            Purchase.status == PurchaseStatus.PAID
        )
    )

    # Total de clientes registrados
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
        "JPEG": ".jpg",
        "PNG": ".png",
        "WEBP": ".webp",
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
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo no es una imagen válida.",
        )

    if image_format not in allowed_formats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se permiten imágenes JPG, PNG o WEBP.",
        )

    image_dir = Path("storage/raffle-images")
    image_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex}{allowed_formats[image_format]}"
    destination = image_dir / filename
    old_image_path = raffle.image_path

    try:
        destination.write_bytes(content)

        raffle.image_path = f"/storage/raffle-images/{filename}"

        log_admin_action(
            db=db,
            admin_id=current_admin.id,
            action="RAFFLE_IMAGE_UPDATED",
            entity_type="raffle",
            entity_id=raffle.id,
            details={
                "image_path": raffle.image_path,
            },
        )

        db.commit()
        db.refresh(raffle)

    except Exception:
        db.rollback()
        destination.unlink(missing_ok=True)
        raise

    # Eliminar la imagen anterior solo si pertenece
    # a la carpeta exclusiva de imágenes de rifas.
    if old_image_path:
        old_filename = Path(old_image_path).name
        old_file = image_dir / old_filename

        if (
            old_image_path.startswith("/storage/raffle-images/")
            and old_file != destination
            and old_file.is_file()
        ):
            old_file.unlink(missing_ok=True)

    return {
        "message": "Imagen de la rifa actualizada correctamente.",
        "raffle_id": raffle.id,
        "image_path": raffle.image_path,
    }