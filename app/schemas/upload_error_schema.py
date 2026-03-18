"""Pydantic schemas for upload error rows."""

from datetime import datetime

from pydantic import BaseModel


class UploadErrorResponse(BaseModel):
    id: int
    upload_id: int
    row_number: int
    error_message: str
    raw_data: str | None
    created_at: datetime

    model_config = {"from_attributes": True}

