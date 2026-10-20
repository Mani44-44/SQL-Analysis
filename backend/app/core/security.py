"""Password hashing (argon2) and session tokens (JWT, HS256)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

SESSION_COOKIE = "askdata_session"
_hasher = PasswordHasher()
DEFAULT_SECRET = "dev-insecure-placeholder-change-me-before-deploying"  # noqa: S105 - refused in prod


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_token(user_id: str, *, ttl: timedelta | None = None) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + (ttl or timedelta(hours=s.jwt_ttl_hours))).timestamp()),
        "typ": "session",
    }
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm="HS256")


def decode_token(token: str) -> str | None:
    """Return the user id for a valid, unexpired session token, else None."""
    try:
        payload = jwt.decode(
            token,
            get_settings().jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "session":
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None
