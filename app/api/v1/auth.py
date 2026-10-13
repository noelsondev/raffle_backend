from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token, verify_password
from app.models import Admin
from app.schemas.auth import LoginRequest, TokenResponse
from app.api.dependencies import get_current_admin


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


@router.post("/login", response_model=TokenResponse)
def login(
    data: LoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    admin = db.scalar(
        select(Admin).where(Admin.email == data.email)
    )

    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas.",
        )

    if not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El administrador está inactivo.",
        )

    if not verify_password(data.password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas.",
        )

    access_token = create_access_token(
        subject=str(admin.id)
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
    )

@router.get("/me")
def get_me(
    current_admin: Admin = Depends(get_current_admin),
):
    return {
        "id": current_admin.id,
        "name": current_admin.name,
        "email": current_admin.email,
        "is_active": current_admin.is_active,
    }