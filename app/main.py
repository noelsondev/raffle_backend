
from fastapi import FastAPI
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.auth import router as auth_router
from app.api.v1.raffles import router as raffles_router
from app.api.v1.customers import router as customers_router
from app.api.v1.purchases import router as purchases_router
from app.api.v1.payments import router as payments_router
from app.api.v1.tickets import router as tickets_router
from app.api.v1.draws import router as draws_router
from app.api.v1.audit_logs import router as audit_logs_router

from app.core.database import engine

from pathlib import Path
from fastapi.staticfiles import StaticFiles

app = FastAPI(
    title="Rifa API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


BASE_DIR = Path(__file__).resolve().parent.parent

STORAGE_DIR = BASE_DIR / "storage"
RAFFLE_IMAGES_DIR = STORAGE_DIR / "raffle-images"

RAFFLE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

app.mount(
    "/storage",
    StaticFiles(directory=str(STORAGE_DIR)),
    name="storage",
)


app.include_router(auth_router, prefix="/api/v1")
app.include_router(raffles_router, prefix="/api/v1")
app.include_router(customers_router, prefix="/api/v1")
app.include_router(purchases_router, prefix="/api/v1")
app.include_router(payments_router, prefix="/api/v1")
app.include_router(tickets_router, prefix="/api/v1")
app.include_router(draws_router, prefix="/api/v1")
app.include_router(audit_logs_router, prefix="/api/v1")


@app.get("/")
def root():
    return {
        "message": "Rifa API funcionando"
    }


@app.get("/health")
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {
            "status": "ok",
            "database": "connected",
        }

    except Exception:
        return {
            "status": "error",
            "database": "disconnected",
        }
