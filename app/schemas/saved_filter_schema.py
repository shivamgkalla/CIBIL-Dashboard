"""Pydantic schemas for saved customer search filters."""

from datetime import datetime

from pydantic import BaseModel


class SavedFilterCreateRequest(BaseModel):
    name: str
    filters: dict


class SavedFilterResponse(BaseModel):
    id: int
    name: str
    filters: dict
    created_at: datetime

    model_config = {"from_attributes": True}

