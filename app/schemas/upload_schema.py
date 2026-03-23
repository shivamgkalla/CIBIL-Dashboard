"""Pydantic schemas for upload responses."""

from pydantic import BaseModel, Field


class UploadAcceptedResponse(BaseModel):
    """Returned immediately when an upload is accepted for background processing."""

    message: str = Field(
        ...,
        examples=["Upload accepted for processing"],
        description="Acknowledgement message.",
    )
    upload_id: int = Field(
        ...,
        examples=[42],
        description="ID to poll for progress via GET /upload/status/{upload_id}.",
    )


class UploadStatusResponse(BaseModel):
    """Progress and result of a background upload."""

    upload_id: int = Field(..., description="Upload history ID.")
    status: str = Field(
        ...,
        examples=["processing"],
        description="Current status: processing, success, partial, or failed.",
    )
    progress_current: int = Field(
        ...,
        examples=[25000],
        description="Number of rows processed so far.",
    )
    progress_total: int = Field(
        ...,
        examples=[540234],
        description="Total rows detected in the main file (0 if still counting).",
    )
    records_inserted: int = Field(
        ...,
        examples=[24800],
        description="Rows successfully inserted so far.",
    )
    records_failed: int = Field(
        ...,
        examples=[200],
        description="Rows that failed so far.",
    )
