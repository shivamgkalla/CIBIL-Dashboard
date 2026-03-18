"""Pydantic schemas for customer historical timeline across snapshots."""

from datetime import datetime

from pydantic import BaseModel, Field


class CustomerTimelineEntry(BaseModel):
    """Single timeline entry representing a snapshot row (joined with identity if present)."""

    snapshot_id: int | None = Field(None, description="Snapshot identifier.")
    uploaded_at: datetime | None = Field(
        None,
        description="Timestamp when this snapshot was uploaded (from upload history).",
    )
    rpt_dt: str | None = Field(
        None,
        description="Report date from the snapshot (YYYY-MM-DD when available).",
        examples=["2025-01-31"],
    )
    income: str | None = Field(
        None,
        description="Reported income string from the bureau file.",
        examples=["75000"],
    )
    bank_type: str | None = Field(
        None,
        description="Bank type flag as provided in main data.",
        examples=["PSU"],
    )
    occup_status_cd: str | None = Field(
        None,
        description="Occupation status code from main data.",
        examples=["SAL"],
    )

    # Identity data (optional; may not exist for every snapshot)
    pan: str | None = Field(None, description="Permanent Account Number.", examples=["ABCDE1234F"])
    passport: str | None = Field(None, description="Passport number.")
    voter_id: str | None = Field(None, description="Voter ID.")
    uid: str | None = Field(None, description="UID identifier when present.")
    driving_license: str | None = Field(None, description="Driving license number.")
    ration_card: str | None = Field(None, description="Ration card identifier.")


class CustomerTimelineResponse(BaseModel):
    """Historical timeline response for a customer across all snapshots."""

    customer_id: str
    timeline: list[CustomerTimelineEntry]

