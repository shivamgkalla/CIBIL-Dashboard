"""User and admin routes (shared dashboard)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.role_checker import admin_or_user
from app.models.user_model import User
from app.schemas.dashboard_schema import DashboardResponse
from app.services import dashboard_service

router = APIRouter(prefix="/user", tags=["User"])


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="User dashboard analytics overview.",
    responses={
        200: {
            "description": "Aggregated analytics for the latest snapshot.",
        },
        403: {"description": "Insufficient permissions"},
    },
)
def user_dashboard(
    current_user: Annotated[User, Depends(admin_or_user)],
    db: Session = Depends(get_db),
) -> DashboardResponse:
    """Accessible for both **admin** and **user** roles."""
    return dashboard_service.get_dashboard_data(db)
