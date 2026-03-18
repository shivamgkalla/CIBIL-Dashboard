"""Pydantic schemas for login activity."""

from datetime import datetime

from pydantic import BaseModel


class LoginActivityResponse(BaseModel):
    """Schema returned for login activity audit."""

    id: int
    user_id: int | None
    identifier: str
    email: str | None
    login_time: datetime
    ip_address: str | None
    user_agent: str | None
    success: bool
    failure_reason: str | None = None

    model_config = {"from_attributes": True}

