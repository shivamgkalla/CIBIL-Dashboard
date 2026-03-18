"""Authentication business logic."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user_model import User, UserRole
from app.schemas.user_schema import RoleEnum, UserRegister, UserResponse

settings = get_settings()


def create_user(
    db: Session,
    data: UserRegister,
    *,
    created_by_admin: bool = False,
) -> User:
    """
    Create a new user.

    Default role is user. Only an admin can create another admin (enforced by caller).
    """
    if data.role == RoleEnum.ADMIN and not created_by_admin:
        raise ValueError("Only an admin can create a user with admin role.")

    user = User(
        username=data.username,
        email=data.email,
        hashed_password=hash_password(data.password),
        role=UserRole(data.role.value),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _find_user_by_email(db: Session, email: str) -> User | None:
    """Look up a user by email."""
    return db.query(User).filter(User.email == email).first()


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """Verify email and password; return User if valid, else None."""
    user = _find_user_by_email(db, email)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def authenticate_user_with_reason(
    db: Session, email: str, password: str
) -> tuple[User | None, str | None]:
    """
    Authenticate and provide a failure reason for audit logging.

    Returns:
        (user, failure_reason)
        - user: User when authenticated, else None
        - failure_reason: one of {"user_not_found", "invalid_credentials"} when failed, else None
    """
    user = _find_user_by_email(db, email)
    if not user:
        return None, "user_not_found"
    if not verify_password(password, user.hashed_password):
        return None, "invalid_credentials"
    user.last_login = datetime.now(timezone.utc)
    return user, None


def generate_token(user: User) -> str:
    """Generate JWT access token for the user."""
    expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return create_access_token(
        subject=user.id,
        username=user.username,
        role=user.role.value,
        expires_delta=expires,
    )


def get_user_by_id(db: Session, user_id: int) -> User | None:
    """Get user by primary key."""
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_username(db: Session, username: str) -> User | None:
    """Get user by username."""
    return db.query(User).filter(User.username == username).first()
