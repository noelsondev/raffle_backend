
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import logging
import secrets
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, Response
from PIL import Image
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.core.database import get_db
from app.models.admin import Admin
from app.models.customer import Customer
from app.models.payment import Payment, PaymentStatus
from app.models.purchase import Purchase, PurchaseStatus
from app.models.raffle import Raffle, RaffleStatus
from app.models.ticket import Ticket, TicketStatus
from app.schemas.payment import PaymentReview
from app.services.audit import log_admin_action
from app.services.supabase_storage import get_supabase_client


router = APIRouter(prefix="/payments", tags=["Payments"])

PROOF_DIR = Path("storage/payment-proofs")
PROOF_BUCKET = "payment-proofs"
MAX_FILE_SIZE = 5 * 1024 * 1024

ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def delete_supabase_proof(object_path: str) -> None:
    """Intenta eliminar un comprobante de Supabase."""
    try:
        client = get_supabase_client()
        client.storage.from_(PROOF_BUCKET).remove([object_path])
    except Exception:
        logging.exception(
            "No se pudo eliminar el comprobante %s de Supabase.",
            object_path,
        )


@router.post("/proof", status_code=status.HTTP_201_CREATED)
async def upload_payment_proof(
    reference: str = Form(..., min_length=16, max_length=16),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    reference = reference.strip().upper()

    if any(
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
        .with_for_update()
        .first()
    )

    if purchase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Referencia de pago no encontrada.",
        )

    if purchase.status != PurchaseStatus.PENDING_PAYMENT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta compra no acepta comprobantes en su estado actual.",
        )

    existing_payment = (
        db.query(Payment)
        .filter(Payment.purchase_id == purchase.id)
        .first()
    )

    if existing_payment is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya se ha enviado un comprobante para esta compra.",
        )

    extension = ALLOWED_TYPES.get(file.content_type or "")

    if extension is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Formato no permitido. Usa JPG, PNG o WEBP.",
        )

    object_path = None
    uploaded_to_storage = False

    try:
        content = await file.read(MAX_FILE_SIZE + 1)

        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El archivo está vacío.",
            )

        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="El comprobante no puede superar los 5 MB.",
            )

        try:
            with Image.open(BytesIO(content)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("Formato de imagen no permitido.")
                image.verify()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El archivo no contiene una imagen válida.",
            ) from exc

        # Cada comprobante tiene una ruta única dentro del bucket privado.
        object_path = (
            f"{purchase.id}/{uuid4().hex}{extension}"
        )

        client = get_supabase_client()

        client.storage.from_(PROOF_BUCKET).upload(
            path=object_path,
            file=content,
            file_options={
                "content-type": file.content_type,
                "upsert": "false",
            },
        )

        uploaded_to_storage = True

        payment = Payment(
            purchase_id=purchase.id,
            # Guardamos la ruta del objeto, nunca una URL pública.
            proof_path=object_path,
            status=PaymentStatus.PENDING,
        )

        purchase.status = PurchaseStatus.PAYMENT_SUBMITTED

        db.add(payment)
        db.commit()
        db.refresh(payment)

        return {
            "message": "Comprobante recibido. Está pendiente de revisión.",
            "payment_id": payment.id,
            "purchase_id": purchase.id,
            "status": payment.status.value,
        }

    except HTTPException:
        db.rollback()

        if uploaded_to_storage and object_path:
            delete_supabase_proof(object_path)

        raise

    except Exception as exc:
        db.rollback()

        if uploaded_to_storage and object_path:
            delete_supabase_proof(object_path)

        logging.exception("Error registrando el comprobante.")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo registrar el comprobante.",
        ) from exc

    finally:
        await file.close()


@router.get("/pending")
def list_pending_payments(
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    results = (
        db.query(Payment, Purchase, Customer, Raffle)
        .join(Purchase, Payment.purchase_id == Purchase.id)
        .join(Customer, Purchase.customer_id == Customer.id)
        .join(Raffle, Purchase.raffle_id == Raffle.id)
        .filter(
            Payment.status == PaymentStatus.PENDING,
            Purchase.status == PurchaseStatus.PAYMENT_SUBMITTED,
        )
        .order_by(Payment.created_at.asc())
        .all()
    )

    return [
        {
            "payment_id": payment.id,
            "purchase_id": purchase.id,
            "customer_name": customer.name,
            "customer_phone": customer.phone,
            "raffle_title": raffle.title,
            "quantity": purchase.quantity,
            "unit_price": str(purchase.unit_price),
            "total_amount": str(purchase.total_amount),
            "payment_reference": purchase.payment_reference,
            "proof_path": payment.proof_path,
            "payment_status": payment.status.value,
            "purchase_status": purchase.status.value,
            "submitted_at": payment.created_at,
        }
        for payment, purchase, customer, raffle in results
    ]


@router.get("/{payment_id}/proof")
def view_payment_proof(
    payment_id: int,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    payment = (
        db.query(Payment)
        .filter(Payment.id == payment_id)
        .first()
    )

    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pago no encontrado.",
        )

    stored_path = payment.proof_path

    if not stored_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El pago no tiene un comprobante registrado.",
        )

    suffix = Path(stored_path).suffix.lower()
    media_type = MEDIA_TYPES.get(suffix)

    if media_type is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Formato del comprobante no permitido.",
        )

    # Compatibilidad con comprobantes antiguos guardados en el disco.
    legacy_path = Path(stored_path)
    legacy_prefix = Path("storage") / "payment-proofs"

    if (
        not legacy_path.is_absolute()
        and legacy_path.parts[:2] == legacy_prefix.parts
    ):
        proof_path = legacy_path.resolve()
        allowed_dir = PROOF_DIR.resolve()

        if not proof_path.is_relative_to(allowed_dir):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ruta del comprobante no permitida.",
            )

        if not proof_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El archivo antiguo del comprobante no existe.",
            )

        return FileResponse(
            path=proof_path,
            media_type=media_type,
            content_disposition_type="inline",
            headers={
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, no-store",
            },
        )

    # Las rutas nuevas son claves privadas de Supabase Storage.
    try:
        client = get_supabase_client()

        content = client.storage.from_(PROOF_BUCKET).download(
            stored_path
        )

        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": "inline",
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, no-store",
            },
        )

    except Exception as exc:
        logging.exception(
            "Error recuperando el comprobante del pago %s.",
            payment_id,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo recuperar el comprobante almacenado.",
        ) from exc


@router.patch("/{payment_id}/review")
def review_payment(
    payment_id: int,
    data: PaymentReview,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    if data.decision not in {"approve", "reject"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La decisión debe ser approve o reject.",
        )

    payment = (
        db.query(Payment)
        .filter(Payment.id == payment_id)
        .with_for_update()
        .first()
    )

    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pago no encontrado.",
        )

    if payment.status != PaymentStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este pago ya fue revisado.",
        )

    purchase = (
        db.query(Purchase)
        .filter(Purchase.id == payment.purchase_id)
        .with_for_update()
        .first()
    )

    if purchase is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Compra no encontrada.",
        )

    if purchase.status != PurchaseStatus.PAYMENT_SUBMITTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La compra no está pendiente de revisión de pago.",
        )

    assigned_numbers = []

    try:
        if data.decision == "approve":
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

            available_numbers = [
                number
                for number in range(1, raffle.total_tickets + 1)
                if number not in existing_numbers
            ]

            if len(available_numbers) < purchase.quantity:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "No hay suficientes boletos disponibles "
                        "para completar esta compra."
                    ),
                )

            assigned_numbers = secrets.SystemRandom().sample(
                available_numbers,
                k=purchase.quantity,
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

            payment.status = PaymentStatus.VERIFIED
            purchase.status = PurchaseStatus.PAID

        else:
            payment.status = PaymentStatus.REJECTED
            purchase.status = PurchaseStatus.REJECTED

        payment.reviewed_by = current_admin.id
        payment.reviewed_at = datetime.now(timezone.utc)

        log_admin_action(
            db=db,
            admin_id=current_admin.id,
            action=(
                "PAYMENT_APPROVED"
                if data.decision == "approve"
                else "PAYMENT_REJECTED"
            ),
            entity_type="payment",
            entity_id=payment.id,
            details={
                "purchase_id": purchase.id,
                "decision": data.decision,
                "reason": (
                    data.reason
                    if data.decision == "reject"
                    else None
                ),
                "assigned_ticket_numbers": sorted(assigned_numbers),
            },
        )

        # Pago, compra, boletos y auditoría se guardan juntos.
        db.commit()
        db.refresh(payment)
        db.refresh(purchase)

    except HTTPException:
        db.rollback()
        raise

    except Exception as exc:
        db.rollback()
        logging.exception(
            "Error revisando el pago %s.",
            payment_id,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo guardar la revisión.",
        ) from exc

    return {
        "message": (
            "Pago aprobado y boletos asignados."
            if data.decision == "approve"
            else "Pago rechazado."
        ),
        "payment_id": payment.id,
        "purchase_id": purchase.id,
        "payment_status": payment.status.value,
        "purchase_status": purchase.status.value,
        "assigned_ticket_numbers": sorted(assigned_numbers),
        "reviewed_by": current_admin.id,
        "reviewed_at": payment.reviewed_at,
        "reason": data.reason if data.decision == "reject" else None,
    }
