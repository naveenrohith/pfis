"""Authentication, authorization, and secret-handling helpers for PFIS."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from secrets import compare_digest, token_bytes
from typing import Optional

import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.user import User


PASSWORD_ITERATIONS = 100_000
bearer_scheme = HTTPBearer(auto_error=False)


def _derived_fernet_key(secret: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())


def get_cipher() -> Fernet:
    settings = get_settings()
    raw_key = (settings.TOKEN_ENCRYPTION_KEY or "").strip()
    key = raw_key.encode("utf-8") if raw_key else _derived_fernet_key(settings.SECRET_KEY)
    return Fernet(key)


def encrypt_secret(value: Optional[str]) -> Optional[str]:
    """Encrypt secrets stored at rest, preserving legacy plaintext if absent."""
    if not value:
        return value
    if value.startswith("enc:"):
        return value
    token = get_cipher().encrypt(value.encode("utf-8")).decode("utf-8")
    return f"enc:{token}"


def decrypt_secret(value: Optional[str]) -> Optional[str]:
    """Decrypt stored secrets; return legacy plaintext values unchanged."""
    if not value:
        return value
    if not value.startswith("enc:"):
        return value
    token = value[4:]
    try:
        return get_cipher().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise HTTPException(status_code=500, detail="Invalid encrypted credential") from exc


def hash_password(password: str) -> str:
    salt = token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return "pbkdf2_sha256${iterations}${salt}${digest}".format(
        iterations=PASSWORD_ITERATIONS,
        salt=salt.hex(),
        digest=base64.b64encode(digest).decode("utf-8"),
    )


def verify_password(password: str, stored_hash: Optional[str]) -> bool:
    if not stored_hash:
        return False
    try:
        algorithm, iterations, salt_hex, expected_digest = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return compare_digest(base64.b64encode(derived).decode("utf-8"), expected_digest)
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "exp": expires_at,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        ) from exc


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None

    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")

    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def get_current_user(
    current_user: User | None = Depends(get_current_user_optional),
) -> User:
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return current_user


def resolve_user_scope(requested_user_id: Optional[str], current_user: Optional[User]) -> str:
    """Resolve effective user access, honoring auth when present or required."""
    settings = get_settings()

    if current_user is not None:
        if requested_user_id and requested_user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User scope mismatch")
        return current_user.id

    if settings.AUTH_REQUIRED:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    if not requested_user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    return requested_user_id


def ensure_user_owns_resource(resource_user_id: str, current_user: Optional[User]) -> None:
    """Enforce ownership checks when auth is active or a user token is supplied."""
    settings = get_settings()
    if current_user is None and not settings.AUTH_REQUIRED:
        return
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    if resource_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")