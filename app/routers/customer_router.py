"""Read-optimized customer and upload history APIs."""

from typing import Annotated
import io
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.role_checker import admin_or_user, get_current_user
from app.models.user_model import User
from app.services.customer_view_activity_service import log_customer_view
from app.services import customer_service
from app.services.pdf_service import generate_customer_pdf
from app.schemas.customer_schema import (
    CustomerDetailResponse,
    CustomerSearchPage,
    UploadHistoryResponse,
)
from app.schemas.chart_schema import ChartPoint
from app.schemas.customer_timeline_schema import CustomerTimelineResponse
from app.schemas.customer_summary_schema import CustomerSummaryAnalyticsResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Customers"])


DbSessionDep = Annotated[Session, Depends(get_db)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]
AdminOrUserDep = Annotated[User, Depends(admin_or_user)]


@router.get(
    "/customers/search",
    response_model=CustomerSearchPage,
    summary="Search customers across latest snapshot",
)
def search_customers(
    db: DbSessionDep,
    current_user: CurrentUserDep,
    customer_id: str | None = Query(
        default=None,
        description="Filter by customer_id.",
    ),
    pan: str | None = Query(
        default=None,
        description="Filter by PAN from identity data.",
    ),
    phone: str | None = Query(
        default=None,
        description="Filter by phone number from identity data.",
    ),
    acct_key: str | None = Query(
        default=None,
        description="Filter by account key.",
    ),
    bank_type: str | None = Query(
        default=None,
        description="Filter by bank_type flag.",
    ),
    occup_status_cd: str | None = Query(
        default=None,
        description="Filter by occupation status code from main data.",
    ),
    income_min: int | None = Query(
        default=None,
        description="Minimum income (inclusive). Parsed as integer.",
    ),
    income_max: int | None = Query(
        default=None,
        description="Maximum income (inclusive). Parsed as integer.",
    ),
    rpt_dt_from: str | None = Query(
        default=None,
        description="Start of report date range (YYYY-MM-DD).",
    ),
    rpt_dt_to: str | None = Query(
        default=None,
        description="End of report date range (YYYY-MM-DD).",
    ),
    last_customer_id: str | None = Query(
        default=None,
        description=(
            "Keyset pagination cursor. When provided, returns rows with "
            "customer_id > last_customer_id, ordered by customer_id."
        ),
    ),
    page: int = Query(
        default=1,
        ge=1,
        description="1-based page number for pagination.",
    ),
    page_size: int = Query(
        default=50,
        ge=1,
        le=500,
        description="Number of rows per page (max 500).",
    ),
) -> CustomerSearchPage:
    """Search customers across main and identity data using the latest snapshot only."""
    if income_min is not None and income_max is not None and income_min > income_max:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="income_min cannot be greater than income_max",
        )

    if rpt_dt_from is not None and rpt_dt_to is not None and rpt_dt_from > rpt_dt_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="rpt_dt_from cannot be greater than rpt_dt_to",
        )
    return customer_service.search_customers(
        db=db,
        customer_id=customer_id,
        pan=pan,
        phone=phone,
        acct_key=acct_key,
        bank_type=bank_type,
        occup_status_cd=occup_status_cd,
        income_min=income_min,
        income_max=income_max,
        rpt_dt_from=rpt_dt_from,
        rpt_dt_to=rpt_dt_to,
        last_customer_id=last_customer_id,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/customers/{customer_id}",
    response_model=list[CustomerDetailResponse],
    summary="Get full joined records for a customer",
)
def get_customer_details(
    customer_id: str,
    db: DbSessionDep,
    current_user: CurrentUserDep,
) -> list[CustomerDetailResponse]:
    """Return all joined main + identity records for a specific customer."""
    results = customer_service.get_customer_details(db, customer_id)
    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No records found for customer_id={customer_id}",
        )
    try:
        with db.begin_nested():
            log_customer_view(
                db=db,
                user_id=current_user.id,
                customer_id=customer_id,
            )
        db.commit()
    except Exception:
        logger.warning(
            "Failed to log customer view for user_id=%s, customer_id=%s",
            current_user.id, customer_id, exc_info=True,
        )
        db.rollback()
    return results


@router.get(
    "/customers/{customer_id}/timeline",
    response_model=CustomerTimelineResponse,
    summary="Get full historical timeline for a customer across snapshots",
)
def get_customer_timeline(
    customer_id: str,
    db: DbSessionDep,
    current_user: AdminOrUserDep,
) -> CustomerTimelineResponse:
    """Return a stable, ordered timeline for a customer across all snapshots."""
    timeline = customer_service.get_customer_timeline(db, customer_id)
    if not timeline.timeline:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No records found for customer_id={customer_id}",
        )
    try:
        with db.begin_nested():
            log_customer_view(
                db=db,
                user_id=current_user.id,
                customer_id=customer_id,
            )
        db.commit()
    except Exception:
        logger.warning(
            "Failed to log customer view for user_id=%s, customer_id=%s",
            current_user.id, customer_id, exc_info=True,
        )
        db.rollback()
    return timeline


@router.get(
    "/customers/{customer_id}/income-trend",
    response_model=list[ChartPoint],
    summary="Get chart-ready income trend for a customer",
)
def get_income_trend(
    customer_id: str,
    db: DbSessionDep,
    current_user: AdminOrUserDep,
) -> list[ChartPoint]:
    """Return chart-ready income time series for a customer across all snapshots."""
    return customer_service.get_income_trend(db, customer_id)


@router.get(
    "/customers/{customer_id}/bank-trend",
    response_model=list[ChartPoint],
    summary="Get chart-ready bank type trend for a customer",
)
def get_bank_trend(
    customer_id: str,
    db: DbSessionDep,
    current_user: AdminOrUserDep,
) -> list[ChartPoint]:
    """Return chart-ready bank_type changes over time for a customer."""
    return customer_service.get_bank_trend(db, customer_id)


@router.get(
    "/customers/{customer_id}/summary",
    response_model=CustomerSummaryAnalyticsResponse,
    summary="Get customer summary analytics",
)
def get_customer_summary(
    customer_id: str,
    db: DbSessionDep,
    current_user: AdminOrUserDep,
) -> CustomerSummaryAnalyticsResponse:
    """Return analytical insights for a customer_id using existing data."""
    return customer_service.get_customer_summary_analytics(db, customer_id)


@router.get(
    "/customers/export/csv",
    summary="Export filtered customers as CSV",
)
def export_customers_csv(
    db: DbSessionDep,
    current_user: CurrentUserDep,
    customer_id: str | None = Query(
        default=None,
        description="Filter by customer_id.",
    ),
    pan: str | None = Query(
        default=None,
        description="Filter by PAN from identity data.",
    ),
    phone: str | None = Query(
        default=None,
        description="Filter by phone number from identity data.",
    ),
    acct_key: str | None = Query(
        default=None,
        description="Filter by account key.",
    ),
    bank_type: str | None = Query(
        default=None,
        description="Filter by bank_type flag.",
    ),
    occup_status_cd: str | None = Query(
        default=None,
        description="Filter by occupation status code from main data.",
    ),
    income_min: int | None = Query(
        default=None,
        description="Minimum income (inclusive). Parsed as integer.",
    ),
    income_max: int | None = Query(
        default=None,
        description="Maximum income (inclusive). Parsed as integer.",
    ),
    rpt_dt_from: str | None = Query(
        default=None,
        description="Start of report date range (YYYY-MM-DD).",
    ),
    rpt_dt_to: str | None = Query(
        default=None,
        description="End of report date range (YYYY-MM-DD).",
    ),
):
    """Stream a CSV export of customers using the same filters as the search API."""
    if income_min is not None and income_max is not None and income_min > income_max:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="income_min cannot be greater than income_max",
        )

    if rpt_dt_from is not None and rpt_dt_to is not None and rpt_dt_from > rpt_dt_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="rpt_dt_from cannot be greater than rpt_dt_to",
        )

    return StreamingResponse(
        customer_service.stream_customers_csv(
            db=db,
            customer_id=customer_id,
            pan=pan,
            phone=phone,
            acct_key=acct_key,
            bank_type=bank_type,
            occup_status_cd=occup_status_cd,
            income_min=income_min,
            income_max=income_max,
            rpt_dt_from=rpt_dt_from,
            rpt_dt_to=rpt_dt_to,
        ),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="customers_export.csv"',
        },
    )


@router.get(
    "/customers/{customer_id}/report/pdf",
    summary="Download structured customer report as PDF",
)
def download_customer_report_pdf(
    customer_id: str,
    db: DbSessionDep,
    current_user: AdminOrUserDep,
):
    """Return a bureau-style PDF report for a customer."""
    report_data = customer_service.get_customer_report_data(db, customer_id)
    # When overview has only the id and no accounts, mimic 404 behavior from other endpoints.
    if not report_data.get("accounts"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No records found for customer_id={customer_id}",
        )

    pdf_bytes = generate_customer_pdf(report_data)
    filename = f"customer_{customer_id}_report.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )



@router.get(
    "/uploads/history",
    response_model=list[UploadHistoryResponse],
    summary="List upload history ordered by latest first",
)
def get_upload_history(
    db: DbSessionDep,
    current_user: CurrentUserDep,
    limit: int = Query(default=50, ge=1, le=200, description="Max records to return."),
    offset: int = Query(default=0, ge=0, description="Number of records to skip."),
) -> list[UploadHistoryResponse]:
    """Return upload history rows ordered by uploaded_at descending."""
    return customer_service.get_upload_history(db, limit=limit, offset=offset)

