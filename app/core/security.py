"""Security utilities: password hashing and JWT handling."""

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _truncate_for_bcrypt(password: str) -> str:
    """
    Ensure password length is within bcrypt's 72-byte limit.

    Bcrypt only uses the first 72 bytes; passlib raises if it's longer.
    We proactively truncate the UTF-8 bytes and decode back, ignoring
    any split multi-byte character at the boundary.
    """
    raw = password.encode("utf-8")
    if len(raw) <= 72:
        return password
    trimmed = raw[:72].decode("utf-8", errors="ignore")
    return trimmed


def hash_password(password: str) -> str:
    """Hash a plain-text password using bcrypt with safe truncation."""
    safe_password = _truncate_for_bcrypt(password)
    return pwd_context.hash(safe_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    safe_password = _truncate_for_bcrypt(plain_password)
    return pwd_context.verify(safe_password, hashed_password)


def create_access_token(
    subject: str | int,
    username: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a JWT access token.

    Args:
        subject: User ID (stored as 'sub' in payload, also as user_id for clarity).
        username: Username for payload.
        role: User role (admin or user).
        expires_delta: Optional custom expiration time.

    Returns:
        Encoded JWT string.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode: dict[str, Any] = {
        "sub": str(subject),
        "user_id": subject,
        "username": username,
        "role": role,
        "exp": expire,
        "iat": now.timestamp(),
        "last_activity": now.timestamp(),
    }
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any] | None:
    """
    Decode and validate a JWT access token.

    Returns:
        Payload dict if valid, None otherwise.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None
