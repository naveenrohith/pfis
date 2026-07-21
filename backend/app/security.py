"""Authentication, authorization, and secret-handling helpers for PFIS."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from secrets import compare_digest, token_urlsafe

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.auth import AuthSession
from app.models.user import User

PASSWORD_ITERATIONS = 100_000
_PASSWORD_HASHER = PasswordHasher(time_cost=2, memory_cost=19 * 1024, parallelism=1)
bearer_scheme = HTTPBearer(auto_error=False)


def _derived_fernet_key(secret: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())


def get_cipher() -> Fernet:
    settings = get_settings()
    raw_key = (settings.TOKEN_ENCRYPTION_KEY or "").strip()
    key = raw_key.encode("utf-8") if raw_key else _derived_fernet_key(settings.SECRET_KEY)
    return Fernet(key)


def encrypt_secret(value: str | None) -> str | None:
    """Encrypt secrets stored at rest, preserving legacy plaintext if absent."""
    if not value:
        return value
    if value.startswith("enc:"):
        return value
    token = get_cipher().encrypt(value.encode("utf-8")).decode("utf-8")
    return f"enc:{token}"


def decrypt_secret(value: str | None) -> str | None:
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
    """Hash a password with Argon2id."""
    return _PASSWORD_HASHER.hash(password)


def _verify_legacy_password(password: str, stored_hash: str) -> bool:
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


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    if stored_hash.startswith("$argon2"):
        try:
            return _PASSWORD_HASHER.verify(stored_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            return False
    return _verify_legacy_password(password, stored_hash)


def verify_password_and_update(password: str, stored_hash: str | None) -> tuple[bool, str | None]:
    """Verify a password and return an upgraded Argon2id hash when required."""
    if not verify_password(password, stored_hash):
        return False, None
    if not stored_hash or not stored_hash.startswith("$argon2"):
        return True, hash_password(password)
    try:
        if _PASSWORD_HASHER.check_needs_rehash(stored_hash):
            return True, hash_password(password)
    except InvalidHashError:
        return True, hash_password(password)
    return True, None


def normalize_email(value: str) -> str:
    return value.strip().lower()


def hash_session_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def create_auth_session(
    db: AsyncSession,
    user_id: str,
    *,
    mode: str = "auth",
) -> tuple[str, str, AuthSession]:
    """Create a revocable browser session and return its one-time raw tokens."""
    settings = get_settings()
    session_token = token_urlsafe(48)
    csrf_token = token_urlsafe(32)
    now = datetime.now(UTC)
    session = AuthSession(
        user_id=user_id,
        token_hash=hash_session_token(session_token),
        csrf_token_hash=hash_session_token(csrf_token),
        mode=mode,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.SESSION_ABSOLUTE_HOURS),
    )
    db.add(session)
    await db.flush()
    return session_token, csrf_token, session


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def get_active_auth_session(raw_token: str, db: AsyncSession) -> AuthSession | None:
    result = await db.execute(
        select(AuthSession).where(
            AuthSession.token_hash == hash_session_token(raw_token),
            AuthSession.revoked_at.is_(None),
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        return None

    settings = get_settings()
    now = datetime.now(UTC)
    idle_deadline = _as_utc(session.last_seen_at) + timedelta(minutes=settings.SESSION_IDLE_MINUTES)
    if _as_utc(session.expires_at) <= now or idle_deadline <= now:
        session.revoked_at = now
        await db.commit()
        return None

    if _as_utc(session.last_seen_at) <= now - timedelta(minutes=5):
        session.last_seen_at = now
        await db.commit()
    return session


async def revoke_auth_session(raw_token: str | None, db: AsyncSession) -> None:
    if not raw_token:
        return
    session = await get_active_auth_session(raw_token, db)
    if session is not None:
        session.revoked_at = datetime.now(UTC)
        await db.commit()


async def validate_session_csrf(
    raw_session_token: str,
    raw_csrf_token: str,
    db: AsyncSession,
) -> bool:
    session = await get_active_auth_session(raw_session_token, db)
    return bool(
        session and compare_digest(session.csrf_token_hash, hash_session_token(raw_csrf_token))
    )


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    import uuid

    payload = {
        "sub": user_id,
        "exp": expires_at,
        "iat": datetime.now(UTC),
        "jti": str(uuid.uuid4()),
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
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    user_id: str | None = None
    if credentials is not None:
        payload = decode_access_token(credentials.credentials)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token"
            )
    else:
        settings = get_settings()
        raw_session = request.cookies.get(settings.SESSION_COOKIE_NAME)
        if not raw_session:
            return None
        session = await get_active_auth_session(raw_session, db)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session",
            )
        user_id = session.user_id

    result = await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
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


def resolve_user_scope(requested_user_id: str | None, current_user: User | None) -> str:
    """Resolve effective user access, honoring auth when present or required."""
    settings = get_settings()

    if current_user is not None:
        if requested_user_id and requested_user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User scope mismatch")
        return current_user.id

    if settings.AUTH_REQUIRED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )

    if not requested_user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    return requested_user_id


def ensure_user_owns_resource(resource_user_id: str, current_user: User | None) -> None:
    """Enforce ownership checks when auth is active or a user token is supplied."""
    settings = get_settings()
    if current_user is None and not settings.AUTH_REQUIRED:
        return
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    if resource_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
