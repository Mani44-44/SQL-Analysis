"""Email/password auth with an httpOnly session cookie."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.core.config import get_settings
from app.core.limits import RateLimiter
from app.core.security import SESSION_COOKIE, create_token, hash_password, verify_password
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_login_limiter = RateLimiter(limit=10, window_s=60)


class Credentials(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL.match(v):
            raise ValueError("enter a valid email address")
        return v


class UserOut(BaseModel):
    id: str
    email: str


def _set_session(response: Response, user: User) -> None:
    s = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        create_token(user.id),
        max_age=s.jwt_ttl_hours * 3600,
        httponly=True,
        secure=s.cookie_secure,
        samesite=s.cookie_samesite,
        path="/",
    )


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: Credentials, response: Response, db: Session = Depends(get_db)) -> UserOut:
    exists = db.scalar(select(func.count()).select_from(User).where(User.email == body.email))
    if exists:
        raise HTTPException(status_code=409, detail="an account with this email already exists")
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    _set_session(response, user)
    return UserOut(id=user.id, email=user.email)


@router.post("/login", response_model=UserOut)
def login(body: Credentials, response: Response, db: Session = Depends(get_db)) -> UserOut:
    if _login_limiter.check(f"login:{body.email}") is not None:
        raise HTTPException(
            status_code=429, detail="Too many sign-in attempts. Try again in a minute."
        )
    user = db.scalars(select(User).where(User.email == body.email)).first()
    if user is None or not verify_password(user.password_hash, body.password):
        raise HTTPException(status_code=401, detail="email or password is incorrect")
    _set_session(response, user)
    return UserOut(id=user.id, email=user.email)


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(
        SESSION_COOKIE, path="/", secure=s.cookie_secure, samesite=s.cookie_samesite
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(require_user)) -> UserOut:
    return UserOut(id=user.id, email=user.email)
