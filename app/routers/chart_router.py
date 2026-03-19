"""Global chart endpoints — aggregated visualizations across all customers.

These complement the per-customer chart endpoints in customer_router.py.
Section 3.5 of the PDF requires "filter charts by customer or global filters";
the per-customer endpoints handle the first case, these handle the second.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.role_checker import admin_or_user
from app.models.user_model import User
from app.schemas.chart_schema import ChartPoint
from app.services import customer_service

router = APIRouter(prefix="/charts/global", tags=["Charts (Global)"])


DbSessionDep = Annotated[Session, Depends(get_db)]
AdminOrUserDep = Annotated[User, Depends(admin_or_user)]


@router.get(
    "/income-trend",
    response_model=list[ChartPoint],
    summary="Average income trend across all customers (filterable)",
)
def global_income_trend(
    db: DbSessionDep,
    current_user: AdminOrUserDep,
    bank_type: str | None = Query(
        default=None,
        description="Filter by bank_type.",
    ),
    occup_status_cd: str | None = Query(
        default=None,
        description="Filter by occupation status code.",
    ),
    income_min: int | None = Query(
        default=None,
        description="Minimum income (inclusive).",
    ),
    income_max: int | None = Query(
        default=None,
        description="Maximum income (inclusive).",
    ),
    rpt_dt_from: str | None = Query(
        default=None,
        description="Start of report date range (YYYY-MM-DD).",
    ),
    rpt_dt_to: str | None = Query(
        default=None,
        description="End of report date range (YYYY-MM-DD).",
    ),
) -> list[ChartPoint]:
    """Return average income grouped by RPT_DT across the latest snapshot.

    Supports the same global filters as the search endpoint so the frontend
    can show a chart that reacts to the active filter selection.
    """
    return customer_service.get_global_income_trend(
        db,
        bank_type=bank_type,
        occup_status_cd=occup_status_cd,
        income_min=income_min,
        income_max=income_max,
        rpt_dt_from=rpt_dt_from,
        rpt_dt_to=rpt_dt_to,
    )


@router.get(
    "/bank-distribution",
    response_model=list[ChartPoint],
    summary="Bank type distribution across all customers (filterable)",
)
def global_bank_distribution(
    db: DbSessionDep,
    current_user: AdminOrUserDep,
    occup_status_cd: str | None = Query(
        default=None,
        description="Filter by occupation status code.",
    ),
    income_min: int | None = Query(
        default=None,
        description="Minimum income (inclusive).",
    ),
    income_max: int | None = Query(
        default=None,
        description="Maximum income (inclusive).",
    ),
    rpt_dt_from: str | None = Query(
        default=None,
        description="Start of report date range (YYYY-MM-DD).",
    ),
    rpt_dt_to: str | None = Query(
        default=None,
        description="End of report date range (YYYY-MM-DD).",
    ),
) -> list[ChartPoint]:
    """Return count of records per bank_type across the latest snapshot.

    Useful for pie/bar charts showing bank type distribution, with
    optional filters to narrow the dataset.
    """
    return customer_service.get_global_bank_distribution(
        db,
        occup_status_cd=occup_status_cd,
        income_min=income_min,
        income_max=income_max,
        rpt_dt_from=rpt_dt_from,
        rpt_dt_to=rpt_dt_to,
    )
