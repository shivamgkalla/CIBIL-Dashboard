"""Pydantic schemas for admin activity audit log."""

from datetime import datetime

from pydantic import BaseModel


class AdminActivityResponse(BaseModel):
    """Response schema for an admin activity log entry."""

    id: int
    admin_id: int
    action: str
    target_user_id: int | None
    detail: str | None
    performed_at: datetime

    model_config = {"from_attributes": True}
