"""Pydantic schemas for customer view activity."""

from datetime import datetime

from pydantic import BaseModel


class CustomerViewActivityResponse(BaseModel):
    id: int
    user_id: int
    customer_id: str
    viewed_at: datetime

    model_config = {"from_attributes": True}

