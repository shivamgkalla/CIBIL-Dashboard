"""Pydantic schemas for dashboard analytics responses."""

from datetime import datetime

from pydantic import BaseModel, Field


class DashboardSummary(BaseModel):
    """High-level counters for the latest snapshot."""

    total_customers: int = Field(
        ...,
        description="Distinct customers in the latest snapshot.",
        examples=[125_340],
    )
    total_records: int = Field(
        ...,
        description="Total main_data rows in the latest snapshot.",
        examples=[1_002_345],
    )
    latest_upload_date: datetime | None = Field(
        None,
        description="Timestamp of the most recent upload, if any.",
    )
    average_income: float | None = Field(
        None,
        description="Average income across latest snapshot (null when not available).",
        examples=[75000.5],
    )


class BankTypeDistribution(BaseModel):
    """Aggregation of records by bank_type for the latest snapshot."""

    bank_type: str = Field(
        ...,
        description="Bank type code from main data.",
        examples=["PSU"],
    )
    count: int = Field(
        ...,
        description="Number of records for this bank type in the latest snapshot.",
        examples=[50234],
    )


class RecentUpload(BaseModel):
    """Summary of a recent upload run."""

    upload_id: int = Field(
        ...,
        description="UploadHistory primary key.",
        examples=[42],
    )
    records_inserted: int = Field(
        ...,
        description="Number of records successfully inserted for this upload.",
        examples=[540234],
    )
    uploaded_at: datetime = Field(
        ...,
        description="Timestamp when the upload was created.",
    )


class DashboardResponse(BaseModel):
    """Complete dashboard payload used by both admin and user dashboards."""

    summary: DashboardSummary
    bank_distribution: list[BankTypeDistribution]
    recent_uploads: list[RecentUpload]

