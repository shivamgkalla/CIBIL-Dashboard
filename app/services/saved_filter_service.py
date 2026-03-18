"""Service layer for user-saved customer search filters."""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.saved_filter_model import SavedFilter
from app.schemas.saved_filter_schema import SavedFilterCreateRequest


def create_saved_filter(db: Session, user_id: int, data: SavedFilterCreateRequest) -> SavedFilter:
    saved = SavedFilter(
        user_id=user_id,
        name=data.name,
        filters=data.filters,
    )
    db.add(saved)
    db.commit()
    db.refresh(saved)
    return saved


def get_saved_filters(db: Session, user_id: int) -> list[SavedFilter]:
    return (
        db.query(SavedFilter)
        .filter(SavedFilter.user_id == user_id)
        .order_by(SavedFilter.created_at.desc())
        .all()
    )


def delete_saved_filter(db: Session, user_id: int, filter_id: int) -> None:
    saved = (
        db.query(SavedFilter)
        .filter(SavedFilter.id == filter_id, SavedFilter.user_id == user_id)
        .first()
    )
    if not saved:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved filter not found")

    db.delete(saved)
    db.commit()

