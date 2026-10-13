
import os
from uuid import uuid4
from pathlib import Path

from supabase import create_client


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

BUCKET_NAME = "raffle-images"


def get_supabase_client():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "Faltan las variables de entorno de Supabase."
        )

    return create_client(
        SUPABASE_URL,
        SUPABASE_SERVICE_ROLE_KEY,
    )


def upload_raffle_image(
    file_bytes: bytes,
    original_filename: str,
    content_type: str,
) -> str:
    extension = Path(original_filename).suffix.lower()

    allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}

    if extension not in allowed_extensions:
        raise ValueError("Formato de imagen no permitido.")

    allowed_content_types = {
        "image/jpeg",
        "image/png",
        "image/webp",
    }

    if content_type not in allowed_content_types:
        raise ValueError("El archivo no es una imagen compatible.")

    if not file_bytes:
        raise ValueError("El archivo está vacío.")

    # Límite inicial de 5 MB por imagen.
    if len(file_bytes) > 5 * 1024 * 1024:
        raise ValueError("La imagen no puede superar 5 MB.")

    client = get_supabase_client()

    filename = f"{uuid4().hex}{extension}"
    storage_path = f"raffles/{filename}"

    client.storage.from_(BUCKET_NAME).upload(
        path=storage_path,
        file=file_bytes,
        file_options={
            "content-type": content_type,
            "upsert": "false",
        },
    )

    result = client.storage.from_(BUCKET_NAME).get_public_url(
        storage_path
    )

    if isinstance(result, str):
        return result

    return result["publicUrl"]
