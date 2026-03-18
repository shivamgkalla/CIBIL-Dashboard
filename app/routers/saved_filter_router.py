"""Routes for managing user-saved customer search filters."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.role_checker import get_current_user
from app.models.user_model import User
from app.schemas.saved_filter_schema import SavedFilterCreateRequest, SavedFilterResponse
from app.schemas.user_schema import MessageResponse
from app.services import saved_filter_service

router = APIRouter(tags=["Saved Filters"])

DbSessionDep = Annotated[Session, Depends(get_db)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]


@router.post(
    "/filters",
    response_model=SavedFilterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save a customer search filter preset",
)
def create_filter(
    db: DbSessionDep,
    current_user: CurrentUserDep,
    data: SavedFilterCreateRequest,
) -> SavedFilterResponse:
    saved = saved_filter_service.create_saved_filter(db, current_user.id, data)
    return SavedFilterResponse.model_validate(saved)


@router.get(
    "/filters",
    response_model=list[SavedFilterResponse],
    summary="List current user's saved filter presets",
)
def list_filters(
    db: DbSessionDep,
    current_user: CurrentUserDep,
) -> list[SavedFilterResponse]:
    rows = saved_filter_service.get_saved_filters(db, current_user.id)
    return [SavedFilterResponse.model_validate(r) for r in rows]


@router.delete(
    "/filters/{filter_id}",
    response_model=MessageResponse,
    summary="Delete a saved filter preset (owner only)",
)
def delete_filter(
    filter_id: int,
    db: DbSessionDep,
    current_user: CurrentUserDep,
) -> MessageResponse:
    saved_filter_service.delete_saved_filter(db, current_user.id, filter_id)
    return MessageResponse(message="Saved filter deleted")

