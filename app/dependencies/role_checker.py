"""RBAC dependency: RoleChecker for protecting routes by role."""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import create_access_token, decode_access_token
from app.models.user_model import UserRole
from app.services.auth_service import get_user_by_id
from app.db.database import get_db
from sqlalchemy.orm import Session

http_bearer = HTTPBearer(auto_error=False)


def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(http_bearer)],
    response: Response,
) -> int:
    """
    Extract and validate JWT from Authorization header; return user_id.
    Raises 401 if missing or invalid.
    """
    if not credentials or credentials.credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    now_ts = datetime.now(timezone.utc).timestamp()
    last_activity = payload.get("last_activity")
    if last_activity is None:
        # Backwards compatibility for tokens minted before inactivity support:
        # fall back to iat (may be int timestamp or string).
        last_activity = payload.get("iat")
    try:
        last_activity_ts = float(last_activity)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if (now_ts - last_activity_ts) > 1800:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired due to inactivity",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("user_id") or payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Sliding window refresh: new exp (30 min from now) + new last_activity.
    try:
        new_token = create_access_token(
            subject=user_id,
            username=str(payload.get("username") or ""),
            role=str(payload.get("role") or ""),
            expires_delta=timedelta(minutes=30),
        )
        response.headers["X-New-Token"] = new_token
    except Exception:
        # If refresh fails, keep request valid (do not break endpoint behavior).
        pass

    return int(user_id)


def get_current_user(
    user_id: Annotated[int, Depends(get_current_user_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Load current user from DB; raises 401 if not found."""
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_user_optional(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(http_bearer)],
    db: Annotated[Session, Depends(get_db)],
):
    """Return current user if valid Bearer token present; else None (no 401)."""
    if not credentials or not credentials.credentials:
        return None
    payload = decode_access_token(credentials.credentials)
    if not payload:
        return None
    user_id = payload.get("user_id") or payload.get("sub")
    if user_id is None:
        return None
    return get_user_by_id(db, int(user_id))


class RoleChecker:
    """Dependency class to enforce allowed roles on a route."""

    def __init__(self, allowed_roles: list[UserRole]):
        self.allowed_roles = allowed_roles

    def __call__(self, user=Depends(get_current_user)):
        if user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user


# Reusable dependency instances
admin_only = RoleChecker([UserRole.ADMIN])
admin_or_user = RoleChecker([UserRole.ADMIN, UserRole.USER])
