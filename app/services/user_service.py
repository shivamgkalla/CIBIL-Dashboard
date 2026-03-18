"""Admin-focused user management business logic."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user_model import User, UserRole
from app.schemas.user_schema import RoleEnum, UserCreateRequest, UserUpdateRequest
from app.services.admin_activity_service import log_admin_action
from app.services.auth_service import get_user_by_id


def _ensure_unique_username(db: Session, username: str, *, exclude_user_id: int | None = None) -> None:
    q = db.query(User).filter(User.username == username)
    if exclude_user_id is not None:
        q = q.filter(User.id != exclude_user_id)
    if q.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )


def _ensure_unique_email(db: Session, email: str, *, exclude_user_id: int | None = None) -> None:
    q = db.query(User).filter(User.email == email)
    if exclude_user_id is not None:
        q = q.filter(User.id != exclude_user_id)
    if q.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already exists",
        )


def get_all_users(db: Session) -> list[User]:
    """Return all users ordered by created_at desc."""
    return db.query(User).order_by(User.created_at.desc()).all()


def create_user_admin(db: Session, data: UserCreateRequest, *, current_admin: User) -> User:
    """Create a user as an admin with uniqueness + role enforcement."""
    _ensure_unique_username(db, data.username)
    _ensure_unique_email(db, data.email)

    if data.role == RoleEnum.ADMIN and current_admin.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin can create another admin",
        )

    user = User(
        username=data.username,
        email=data.email,
        hashed_password=hash_password(data.password),
        role=UserRole(data.role.value),
    )
    db.add(user)
    db.flush()
    log_admin_action(
        db,
        admin_id=current_admin.id,
        action="create_user",
        target_user_id=user.id,
        detail=f"Created user '{data.username}' with role '{data.role.value}'",
    )
    db.commit()
    db.refresh(user)
    return user


def update_user_admin(
    db: Session,
    user_id: int,
    data: UserUpdateRequest,
    *,
    current_admin: User,
) -> User:
    """Update user details (partial), hashing password if provided."""
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if data.username is not None and data.username != user.username:
        _ensure_unique_username(db, data.username, exclude_user_id=user.id)
        user.username = data.username

    if data.email is not None and data.email != user.email:
        _ensure_unique_email(db, str(data.email), exclude_user_id=user.id)
        user.email = str(data.email)

    if data.password is not None:
        user.hashed_password = hash_password(data.password)

    if data.role is not None:
        if current_admin.id == user.id and data.role != RoleEnum.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot demote yourself",
            )
        if data.role == RoleEnum.ADMIN and current_admin.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only an admin can assign admin role",
            )
        user.role = UserRole(data.role.value)

    changed = [f for f in ("username", "email", "password", "role") if getattr(data, f) is not None]
    log_admin_action(
        db,
        admin_id=current_admin.id,
        action="update_user",
        target_user_id=user.id,
        detail=f"Updated fields: {', '.join(changed)}" if changed else "No fields changed",
    )
    db.commit()
    db.refresh(user)
    return user


def delete_user_admin(db: Session, user_id: int, *, current_admin: User) -> None:
    """Delete a user (admin-only) with self-delete protection."""
    if current_admin.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot delete yourself",
        )

    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    detail = f"Deleted user '{user.username}' (id={user.id}, role={user.role.value})"
    db.delete(user)
    log_admin_action(
        db,
        admin_id=current_admin.id,
        action="delete_user",
        target_user_id=user_id,
        detail=detail,
    )
    db.commit()

