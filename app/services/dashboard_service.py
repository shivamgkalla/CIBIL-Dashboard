"""Business logic for dashboard analytics endpoints."""

from __future__ import annotations

from sqlalchemy import Float, cast, func
from sqlalchemy.orm import Session

from app.models.main_data_model import MainData
from app.models.upload_history_model import UploadHistory
from app.schemas.dashboard_schema import (
    BankTypeDistribution,
    DashboardResponse,
    DashboardSummary,
    RecentUpload,
)


def get_dashboard_data(db: Session) -> DashboardResponse:
    """Compute aggregated dashboard analytics for the latest snapshot.

    All queries are designed to:
    * Work off the latest snapshot only.
    * Use aggregate functions and grouping to avoid loading ORM objects.
    * Scale to millions of rows with minimal memory usage.
    """
    # Determine the latest snapshot id from main_data.
    latest_snapshot: int | None = db.query(
        func.max(MainData.snapshot_id)
    ).scalar()

    # If there is no snapshot yet, return an empty but well-formed payload.
    if latest_snapshot is None:
        empty_summary = DashboardSummary(
            total_customers=0,
            total_records=0,
            latest_upload_date=None,
            average_income=0,
        )
        return DashboardResponse(
            summary=empty_summary,
            bank_distribution=[],
            recent_uploads=[],
        )

    # Total distinct customers in the latest snapshot.
    total_customers: int = (
        db.query(func.count(func.distinct(MainData.customer_id)))
        .filter(MainData.snapshot_id == latest_snapshot)
        .scalar()
        or 0
    )

    # Total main_data records in the latest snapshot.
    total_records: int = (
        db.query(func.count(MainData.id))
        .filter(MainData.snapshot_id == latest_snapshot)
        .scalar()
        or 0
    )

    # Latest upload date across all uploads using an ordered lookup.
    latest_upload = (
        db.query(UploadHistory)
        .order_by(UploadHistory.uploaded_at.desc())
        .first()
    )
    latest_upload_date = latest_upload.uploaded_at if latest_upload else None

    # Average income in the latest snapshot; income is stored as TEXT and may contain empty strings.
    average_income = db.query(
        func.avg(
            cast(
                func.nullif(MainData.income, ""),
                Float,
            )
        )
    ).filter(MainData.snapshot_id == latest_snapshot).scalar()

    summary = DashboardSummary(
        total_customers=total_customers,
        total_records=total_records,
        latest_upload_date=latest_upload_date,
        average_income = round(float(average_income), 2) if average_income else 0,
    )

    # Bank type distribution for the latest snapshot, ordered by highest count first.
    bank_rows = (
        db.query(MainData.bank_type, func.count(MainData.id))
        .filter(MainData.snapshot_id == latest_snapshot)
        .group_by(MainData.bank_type)
        .order_by(func.count(MainData.id).desc())
        .all()
    )
    bank_distribution = [
        BankTypeDistribution(
            bank_type=bank_type or "UNKNOWN",
            count=count or 0,
        )
        for bank_type, count in bank_rows
    ]

    # Recent uploads (latest 5 entries).
    recent_rows = (
        db.query(
            UploadHistory.id,
            UploadHistory.records_inserted,
            UploadHistory.uploaded_at,
        )
        .order_by(UploadHistory.uploaded_at.desc())
        .limit(5)
        .all()
    )
    recent_uploads = [
        RecentUpload(
            upload_id=row_id,
            records_inserted=records_inserted,
            uploaded_at=uploaded_at,
        )
        for row_id, records_inserted, uploaded_at in recent_rows
    ]

    return DashboardResponse(
        summary=summary,
        bank_distribution=bank_distribution,
        recent_uploads=recent_uploads,
    )

