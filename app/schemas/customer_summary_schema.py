"""Pydantic schemas for customer summary analytics response."""

from pydantic import BaseModel, Field


class ProfileSummary(BaseModel):
    total_accounts: int = Field(0, description="Total account records found for customer.")
    latest_income: float = Field(0, description="Latest parsed income (0 when unavailable).")
    latest_bank_type: str = Field("", description="Latest bank type (empty when unavailable).")
    first_report_date: str = Field("", description="First report date (empty when unavailable).")
    latest_report_date: str = Field("", description="Latest report date (empty when unavailable).")


class IncomeAnalysis(BaseModel):
    avg_income: float = Field(0, description="Average income across snapshots (0 when unavailable).")
    max_income: float = Field(0, description="Maximum income across snapshots (0 when unavailable).")
    min_income: float = Field(0, description="Minimum income across snapshots (0 when unavailable).")
    trend: str = Field("", description="Income trend: increasing/decreasing/stable.")
    volatility: str = Field("", description="Income volatility: low/medium/high.")


class BankAnalysis(BaseModel):
    unique_bank_types: list[str] = Field(default_factory=list, description="Distinct bank types seen.")
    bank_type_change_count: int = Field(0, description="Number of bank type changes across timeline.")
    most_frequent_bank_type: str = Field("", description="Most frequent bank type.")


class IdentityAnalysis(BaseModel):
    identity_types_present: list[str] = Field(
        default_factory=list,
        description="Identity types present in the latest non-null identity snapshot.",
    )
    identity_count: int = Field(0, description="Count of identity types present.")
    has_strong_identity: bool = Field(
        False, description="True when PAN or UID is present in latest identity."
    )
    latest_identity: dict[str, str] = Field(
        default_factory=dict,
        description="Masked latest identity fields that are present (no empty values).",
    )


class TimelineInsights(BaseModel):
    total_snapshots: int = Field(0, description="Total snapshots in timeline.")
    reporting_span_days: int = Field(0, description="Days between first and latest report dates.")
    activity_status: str = Field("", description="active if latest report within 365 days else inactive.")


class CustomerSummaryAnalyticsResponse(BaseModel):
    profile: ProfileSummary = Field(default_factory=ProfileSummary)
    income_analysis: IncomeAnalysis = Field(default_factory=IncomeAnalysis)
    bank_analysis: BankAnalysis = Field(default_factory=BankAnalysis)
    identity_analysis: IdentityAnalysis = Field(default_factory=IdentityAnalysis)
    timeline_insights: TimelineInsights = Field(default_factory=TimelineInsights)

