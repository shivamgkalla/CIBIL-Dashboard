"""Pydantic schemas for optimized customer and upload history APIs."""

from datetime import datetime

from pydantic import BaseModel, Field


class CustomerSearchResponse(BaseModel):
    """Flat view used for fast customer search across latest snapshot."""

    customer_id: str | None = Field(
        None,
        description="Customer identifier from main data.",
        examples=["CUST123"],
    )
    acct_key: str | None = Field(
        None,
        description="Account key for the facility.",
        examples=["ACCT001"],
    )
    bank_type: str | None = Field(
        None,
        description="Bank type flag as provided in main data.",
        examples=["PSU"],
    )
    income: str | None = Field(
        None,
        description="Reported income string from the bureau file.",
        examples=["75000"],
    )
    rpt_dt: str | None = Field(
        None,
        description="Report date from the CIBIL snapshot.",
        examples=["2025-01-31"],
    )
    pan: str | None = Field(
        None,
        description="Permanent Account Number from identity data.",
        examples=["ABCDE1234F"],
    )


class MainDataResponse(BaseModel):
    """Detailed main data row for a customer account."""

    id: int
    acct_key: str | None = None
    customer_id: str | None = None
    income: str | None = None
    income_freq: str | None = None
    occup_status_cd: str | None = None
    rpt_dt: str | None = None
    bank_type: str | None = None
    snapshot_id: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class IdentityDataResponse(BaseModel):
    """Identity enrichment row matching a main data record."""

    id: int
    customer_id: str | None = None
    pan: str | None = None
    passport: str | None = None
    voter_id: str | None = None
    uid: str | None = None
    ration_card: str | None = None
    driving_license: str | None = None
    snapshot_id: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CustomerDetailResponse(BaseModel):
    """Joined view of main and identity data for a customer account."""

    main_data: MainDataResponse
    identity_data: IdentityDataResponse | None = None


class UploadHistoryResponse(BaseModel):
    """Upload history row representation."""

    id: int
    main_filename: str | None = None
    identity_filename: str | None = None
    filenames: str | None = None
    records_inserted: int
    records_failed: int
    uploaded_by: int | None = None
    uploaded_at: datetime
    status: str

    model_config = {"from_attributes": True}


class CustomerSearchPage(BaseModel):
    """Page wrapper for customer search with keyset pagination cursor."""

    data: list[CustomerSearchResponse]
    next_cursor: str | None


