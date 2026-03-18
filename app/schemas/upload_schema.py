"""Pydantic schemas for upload responses."""

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    """Summary of a bulk upload run."""

    message: str = Field(
        ...,
        examples=["Upload completed"],
        description="High-level status message for the upload run.",
    )
    records_inserted: int = Field(
        ...,
        examples=[540234],
        description="Number of successfully persisted joined records.",
    )
    records_failed: int = Field(
        ...,
        examples=[120],
        description="Number of rows that were skipped due to validation/format errors.",
    )
    status: str = Field(
        ...,
        examples=["success"],
        description="Final status for the upload run (success, partial, failed).",
    )

