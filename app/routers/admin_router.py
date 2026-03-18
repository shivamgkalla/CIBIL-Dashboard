"""Admin-only routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.role_checker import admin_only
from app.models.user_model import User
from app.schemas.admin_activity_schema import AdminActivityResponse
from app.schemas.dashboard_schema import DashboardResponse
from app.schemas.customer_view_activity_schema import CustomerViewActivityResponse
from app.schemas.login_activity_schema import LoginActivityResponse
from app.schemas.upload_error_schema import UploadErrorResponse
from app.schemas.user_schema import MessageResponse, UserCreateRequest, UserResponse, UserUpdateRequest
from app.services import dashboard_service
from app.services.admin_activity_service import get_admin_activity
from app.services.customer_view_activity_service import get_customer_view_activity
from app.services.login_activity_service import get_login_activity
from app.services.user_service import (
    create_user_admin,
    delete_user_admin,
    get_all_users,
    update_user_admin,
)
from app.models.upload_error_model import UploadError

router = APIRouter(prefix="/admin", tags=["Admin"])


DbSessionDep = Annotated[Session, Depends(get_db)]
AdminUserDep = Annotated[User, Depends(admin_only)]


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="Admin dashboard analytics overview.",
    responses={
        200: {
            "description": "Aggregated analytics for the latest snapshot.",
        },
        403: {"description": "Insufficient permissions"},
    },
)
def admin_dashboard(
    current_user: AdminUserDep,
    db: DbSessionDep,
) -> DashboardResponse:
    """Accessible only for users with **admin** role."""
    return dashboard_service.get_dashboard_data(db)


@router.get(
    "/login-activity",
    response_model=list[LoginActivityResponse],
    summary="Recent login attempts (admin only).",
    responses={
        200: {
            "description": "Last 50 login attempts ordered by time descending.",
        },
        403: {"description": "Insufficient permissions"},
    },
)
def admin_login_activity(
    current_user: AdminUserDep,
    db: DbSessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[LoginActivityResponse]:
    """Return recent login activity for auditing (admin only)."""
    records = get_login_activity(db, limit=limit, offset=offset)
    return records


@router.get(
    "/customer-view-activity",
    response_model=list[CustomerViewActivityResponse],
    summary="Recent customer view activity (admin only).",
    responses={
        200: {"description": "Customer view logs ordered by time descending."},
        403: {"description": "Insufficient permissions"},
    },
)
def admin_customer_view_activity(
    current_user: AdminUserDep,
    db: DbSessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[CustomerViewActivityResponse]:
    records = get_customer_view_activity(db, limit=limit, offset=offset)
    return records


@router.get(
    "/upload-errors",
    response_model=list[UploadErrorResponse],
    summary="Upload row-level errors for a given upload (admin only).",
    responses={
        200: {"description": "Error rows ordered by created_at descending."},
        403: {"description": "Insufficient permissions"},
    },
)
def admin_upload_errors(
    current_user: AdminUserDep,
    db: DbSessionDep,
    upload_id: int = Query(..., ge=1),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[UploadErrorResponse]:
    rows = (
        db.query(UploadError)
        .filter(UploadError.upload_id == upload_id)
        .order_by(UploadError.created_at.desc(), UploadError.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [UploadErrorResponse.model_validate(r) for r in rows]


@router.get(
    "/users",
    response_model=list[UserResponse],
    summary="List all users (admin only).",
)
def list_users(
    current_user: AdminUserDep,
    db: DbSessionDep,
) -> list[UserResponse]:
    users = get_all_users(db)
    return [UserResponse.model_validate_user(u) for u in users]


@router.post(
    "/users",
    response_model=UserResponse,
    summary="Create a new user (admin only).",
    status_code=201,
)
def create_user(
    payload: UserCreateRequest,
    current_user: AdminUserDep,
    db: DbSessionDep,
) -> UserResponse:
    user = create_user_admin(db, payload, current_admin=current_user)
    return UserResponse.model_validate_user(user)


@router.patch(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="Update user details (admin only).",
)
def patch_user(
    user_id: int,
    payload: UserUpdateRequest,
    current_user: AdminUserDep,
    db: DbSessionDep,
) -> UserResponse:
    user = update_user_admin(db, user_id, payload, current_admin=current_user)
    return UserResponse.model_validate_user(user)


@router.delete(
    "/users/{user_id}",
    response_model=MessageResponse,
    summary="Delete a user (admin only).",
)
def remove_user(
    user_id: int,
    current_user: AdminUserDep,
    db: DbSessionDep,
) -> MessageResponse:
    delete_user_admin(db, user_id, current_admin=current_user)
    return MessageResponse(message="User deleted successfully")


@router.get(
    "/admin-activity",
    response_model=list[AdminActivityResponse],
    summary="Admin action audit log (admin only).",
    responses={
        200: {"description": "Admin actions ordered by time descending."},
        403: {"description": "Insufficient permissions"},
    },
)
def admin_action_activity(
    current_user: AdminUserDep,
    db: DbSessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[AdminActivityResponse]:
    """Return admin CRUD action logs for auditing."""
    return get_admin_activity(db, limit=limit, offset=offset)
