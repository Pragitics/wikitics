from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.application.auth.service import AuthService, serialize_user
from app.infrastructure.db.models import UserModel
from app.infrastructure.db.session import get_db
from app.infrastructure.settings import Settings
from app.interfaces.api.dependencies import get_current_user, settings_dependency

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = Field(min_length=1)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register")
def register(payload: RegisterRequest, db: Session = Depends(get_db), settings: Settings = Depends(settings_dependency)):
    return AuthService(db, settings.secret_key, settings.access_token_ttl_seconds).register(
        payload.email, payload.password, payload.name
    )


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db), settings: Settings = Depends(settings_dependency)):
    return AuthService(db, settings.secret_key, settings.access_token_ttl_seconds).login(payload.email, payload.password)


@router.post("/logout")
def logout() -> dict:
    return {"ok": True}


@router.get("/me")
def me(user: UserModel = Depends(get_current_user)) -> dict:
    return serialize_user(user)
