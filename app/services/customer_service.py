"""Business logic for customer and upload history read APIs."""

from collections import Counter
from collections.abc import Generator, Sequence
from datetime import datetime, timedelta, timezone
import logging

from dateutil.parser import parse

from sqlalchemy import Integer, case, cast, func, literal
from sqlalchemy.orm import Session, Query

from app.models.identity_data_model import IdentityData
from app.models.main_data_model import MainData
from app.models.upload_history_model import UploadHistory
from app.schemas.chart_schema import ChartPoint
from app.schemas.customer_schema import (
    CustomerDetailResponse,
    CustomerSearchPage,
    CustomerSearchResponse,
    IdentityDataResponse,
    MainDataResponse,
    UploadHistoryResponse,
)
from app.schemas.customer_timeline_schema import (
    CustomerTimelineEntry,
    CustomerTimelineResponse,
)
from app.utils.masking import (
    mask_driving_license,
    mask_generic,
    mask_pan,
    mask_passport,
)

log = logging.getLogger(__name__)

ACTIVE_DAYS_THRESHOLD = 365
INCOME_VOLATILITY_LOW = 0.2
INCOME_VOLATILITY_MEDIUM = 0.5


def _norm_str(value: object | None) -> str:
    """Normalize potentially-null values into a stripped string."""
    return ("" if value is None else str(value)).strip()


def _apply_identity_masking(obj: object) -> None:
    """Best-effort in-place masking for identity-like response objects.

    This operates only on response objects (Pydantic models), never DB rows.
    """

    try:
        pan = getattr(obj, "pan", None)
        setattr(obj, "pan", mask_pan(pan))
    except Exception:
        pass
    try:
        uid = getattr(obj, "uid", None)
        setattr(obj, "uid", mask_generic(uid, keep_start=0, keep_end=4))
    except Exception:
        pass
    try:
        passport = getattr(obj, "passport", None)
        setattr(obj, "passport", mask_passport(passport))
    except Exception:
        pass
    try:
        driving_license = getattr(obj, "driving_license", None)
        setattr(obj, "driving_license", mask_driving_license(driving_license))
    except Exception:
        pass
    try:
        voter_id = getattr(obj, "voter_id", None)
        setattr(obj, "voter_id", mask_generic(voter_id, keep_start=2, keep_end=2))
    except Exception:
        pass
    try:
        ration_card = getattr(obj, "ration_card", None)
        setattr(
            obj,
            "ration_card",
            mask_generic(ration_card, keep_start=2, keep_end=2),
        )
    except Exception:
        pass


def _parse_income(value: str | None) -> int | float | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None

    normalized = raw.replace(",", "")
    try:
        return int(normalized)
    except ValueError:
        try:
            return float(normalized)
        except ValueError:
            return None


def _safe_parse_rpt_dt(value: object | None) -> datetime | None:
    """Parse rpt_dt-like values to a naive datetime, or None when invalid."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = parse(raw)
        return parsed.replace(tzinfo=None)
    except Exception:
        return None


def _detail_sort_key(item: CustomerDetailResponse) -> tuple[datetime, int]:
    """Deterministic ordering by rpt_dt then snapshot_id (NULL/invalid first)."""
    main = item.main_data
    dt = _safe_parse_rpt_dt(main.rpt_dt) or datetime.min
    snapshot_id = main.snapshot_id if main.snapshot_id is not None else 0
    return (dt, snapshot_id)


def _get_latest_non_null_identity(
    details: list[CustomerDetailResponse],
) -> IdentityDataResponse | None:
    """Return latest identity with at least one non-empty field (already masked)."""
    for item in sorted(details, key=_detail_sort_key, reverse=True):
        identity_model = item.identity_data
        if identity_model is None:
            continue
        if any(
            [
                identity_model.pan,
                identity_model.uid,
                identity_model.passport,
                identity_model.voter_id,
                identity_model.driving_license,
                identity_model.ration_card,
            ]
        ):
            return identity_model
    return None


def _strip_none_values(value: object) -> object:
    """Recursively drop None values from dicts/lists to avoid nulls in responses."""
    if isinstance(value, dict):
        cleaned: dict[object, object] = {}
        for k, v in value.items():
            if v is None:
                continue
            cv = _strip_none_values(v)
            # Keep empty containers only when they were explicitly set.
            cleaned[k] = cv
        return cleaned
    if isinstance(value, list):
        return [v for v in (_strip_none_values(x) for x in value) if v is not None]
    return value


def _default_summary_sections() -> dict[str, dict[str, object]]:
    """Return defaults for analytics sections (no None leaks)."""
    return {
        "profile": {
            "total_accounts": 0,
            "latest_income": 0,
            "latest_bank_type": "",
            "first_report_date": "",
            "latest_report_date": "",
        },
        "income_analysis": {
            "avg_income": 0,
            "max_income": 0,
            "min_income": 0,
            "trend": "",
            "volatility": "",
        },
        "bank_analysis": {
            "unique_bank_types": [],
            "bank_type_change_count": 0,
            "most_frequent_bank_type": "",
        },
        "identity_analysis": {
            "identity_types_present": [],
            "identity_count": 0,
            "has_strong_identity": False,
            "latest_identity": {},
        },
        "timeline_insights": {
            "total_snapshots": 0,
            "reporting_span_days": 0,
            "activity_status": "",
        },
    }


def _build_profile(
    *,
    sorted_details: list[CustomerDetailResponse],
) -> dict[str, object]:
    profile = _default_summary_sections()["profile"]
    if not sorted_details:
        return profile

    first_detail = sorted_details[0]
    latest_detail = sorted_details[-1]
    profile.update(
        {
            "total_accounts": len(sorted_details),
            "latest_income": _parse_income(latest_detail.main_data.income) or 0,
            "latest_bank_type": _norm_str(latest_detail.main_data.bank_type),
            "first_report_date": _norm_str(first_detail.main_data.rpt_dt),
            "latest_report_date": _norm_str(latest_detail.main_data.rpt_dt),
        }
    )
    return profile


def _build_income_analysis(
    *,
    sorted_details: list[CustomerDetailResponse],
    income_cache_by_idx: list[int | float | None],
) -> dict[str, object]:
    income_analysis = _default_summary_sections()["income_analysis"]
    parsed_incomes: list[int | float] = [v for v in income_cache_by_idx if v is not None]
    if not parsed_incomes:
        return income_analysis

    avg_income = sum(parsed_incomes) / len(parsed_incomes)
    max_income = max(parsed_incomes)
    min_income = min(parsed_incomes)

    # Trend: compare first vs last where an income exists.
    first_income = None
    last_income = None
    for v in income_cache_by_idx:
        if v is not None:
            first_income = v
            break
    for v in reversed(income_cache_by_idx):
        if v is not None:
            last_income = v
            break

    trend = ""
    if len(parsed_incomes) < 2:
        trend = "stable"
    elif first_income is not None and last_income is not None:
        if last_income > first_income:
            trend = "increasing"
        elif last_income < first_income:
            trend = "decreasing"
        else:
            trend = "stable"

    # Volatility based on range vs average.
    volatility = ""
    if avg_income <= 0:
        volatility = ""
    else:
        income_range = max_income - min_income
        ratio = income_range / avg_income
        if ratio < INCOME_VOLATILITY_LOW:
            volatility = "low"
        elif ratio < INCOME_VOLATILITY_MEDIUM:
            volatility = "medium"
        else:
            volatility = "high"

    income_analysis.update(
        {
            "avg_income": round(avg_income, 2),
            "max_income": max_income,
            "min_income": min_income,
            "trend": trend,
            "volatility": volatility,
        }
    )
    return income_analysis


def _build_bank_analysis(
    *,
    timeline: list[CustomerTimelineEntry],
    sorted_details: list[CustomerDetailResponse],
) -> dict[str, object]:
    bank_analysis = _default_summary_sections()["bank_analysis"]

    # Prefer timeline bank types (already ordered by service query); fallback to sorted details.
    bank_types: list[str] = []
    for entry in timeline:
        bt = _norm_str(entry.bank_type)
        if bt:
            bank_types.append(bt)

    if not bank_types:
        for item in sorted_details:
            bt = _norm_str(item.main_data.bank_type)
            if bt:
                bank_types.append(bt)

    if not bank_types:
        return bank_analysis

    unique_bank_types = sorted(set(bank_types))
    changes = 0
    prev = None
    for bt in bank_types:
        if prev is None:
            prev = bt
            continue
        if bt != prev:
            changes += 1
            prev = bt
    most_frequent_bank_type = Counter(bank_types).most_common(1)[0][0]

    bank_analysis.update(
        {
            "unique_bank_types": unique_bank_types,
            "bank_type_change_count": changes,
            "most_frequent_bank_type": most_frequent_bank_type,
        }
    )
    return bank_analysis


def _build_identity_analysis(
    *,
    sorted_details: list[CustomerDetailResponse],
) -> dict[str, object]:
    identity_analysis = _default_summary_sections()["identity_analysis"]
    latest_identity = _get_latest_non_null_identity(sorted_details) if sorted_details else None
    if latest_identity is None:
        return identity_analysis

    identity_fields: dict[str, str] = {
        "pan": _norm_str(latest_identity.pan),
        "uid": _norm_str(latest_identity.uid),
        "passport": _norm_str(latest_identity.passport),
        "voter_id": _norm_str(latest_identity.voter_id),
        "driving_license": _norm_str(latest_identity.driving_license),
        "ration_card": _norm_str(latest_identity.ration_card),
    }
    identity_types_present = sorted([k for k, v in identity_fields.items() if v])
    has_strong_identity = bool(
        identity_fields.get("pan")
        or identity_fields.get("uid")
        or (identity_fields.get("passport") and identity_fields.get("driving_license"))
    )
    identity_analysis.update(
        {
            "identity_types_present": identity_types_present,
            "identity_count": len(identity_types_present),
            "has_strong_identity": has_strong_identity,
            "latest_identity": {k: v for k, v in identity_fields.items() if v},
        }
    )
    return identity_analysis


def _build_timeline_insights(
    *,
    timeline: list[CustomerTimelineEntry],
    parsed_rpt_dt: list[datetime | None],
) -> dict[str, object]:
    timeline_insights = _default_summary_sections()["timeline_insights"]
    timeline_insights["total_snapshots"] = len(timeline)

    rpt_dates: list[datetime] = [d for d in parsed_rpt_dt if d is not None]
    if not rpt_dates:
        return timeline_insights

    first_dt = min(rpt_dates)
    last_dt = max(rpt_dates)
    reporting_span_days = max(0, (last_dt.date() - first_dt.date()).days)

    # All timestamps assumed UTC (naive date comparison).
    activity_status = (
        "active"
        if (datetime.now(timezone.utc).date() - last_dt.date())
        <= timedelta(days=ACTIVE_DAYS_THRESHOLD)
        else "inactive"
    )
    timeline_insights.update(
        {"reporting_span_days": reporting_span_days, "activity_status": activity_status}
    )
    return timeline_insights


def get_customer_summary_analytics(db: Session, customer_id: str) -> dict:
    """Return analytical insights for a customer_id using existing read helpers."""
    log.info("Generating summary", extra={"customer_id": customer_id})
    details = get_customer_details(db, customer_id)
    timeline = get_customer_timeline(db, customer_id).timeline

    defaults = _default_summary_sections()

    if not details and not timeline:
        log.warning("No data for customer", extra={"customer_id": customer_id})
        return defaults

    if len(details) > 5000:
        log.warning(
            "Large dataset for customer",
            extra={"customer_id": customer_id, "details_count": len(details)},
        )

    sorted_details = sorted(details, key=_detail_sort_key)

    # Cache parsed income values by index to avoid repeated parsing.
    income_cache_by_idx: list[int | float | None] = []
    income_parse_failures = 0
    for item in sorted_details:
        raw_income = _norm_str(item.main_data.income)
        parsed = _parse_income(raw_income) if raw_income else None
        if raw_income and parsed is None:
            income_parse_failures += 1
        income_cache_by_idx.append(parsed)
    if income_parse_failures:
        log.debug(
            "Parsing failed",
            extra={"field": "income", "count": income_parse_failures, "customer_id": customer_id},
        )

    # Cache parsed report dates for timeline entries.
    rpt_dt_cache: list[datetime | None] = []
    rpt_dt_parse_failures = 0
    for entry in timeline:
        raw_rpt_dt = _norm_str(entry.rpt_dt)
        parsed_dt = _safe_parse_rpt_dt(raw_rpt_dt) if raw_rpt_dt else None
        if raw_rpt_dt and parsed_dt is None:
            rpt_dt_parse_failures += 1
        rpt_dt_cache.append(parsed_dt)
    if rpt_dt_parse_failures:
        log.debug(
            "Parsing failed",
            extra={"field": "rpt_dt", "count": rpt_dt_parse_failures, "customer_id": customer_id},
        )

    # ------------------------
    profile = _build_profile(sorted_details=sorted_details)
    income_analysis = _build_income_analysis(
        sorted_details=sorted_details, income_cache_by_idx=income_cache_by_idx
    )
    bank_analysis = _build_bank_analysis(timeline=timeline, sorted_details=sorted_details)
    identity_analysis = _build_identity_analysis(sorted_details=sorted_details)
    timeline_insights = _build_timeline_insights(timeline=timeline, parsed_rpt_dt=rpt_dt_cache)

    return _strip_none_values(
        {
            "profile": profile,
            "income_analysis": income_analysis,
            "bank_analysis": bank_analysis,
            "identity_analysis": identity_analysis,
            "timeline_insights": timeline_insights,
        }
    )


def _rpt_dt_sort_key():
    # Push NULL/empty rpt_dt last while keeping deterministic ordering.
    return case(
        (MainData.rpt_dt.is_(None), literal("9999-12-31")),
        (MainData.rpt_dt == "", literal("9999-12-31")),
        else_=MainData.rpt_dt,
    )


def _get_latest_snapshot_id(db: Session) -> int | None:
    """Return the latest successful snapshot id, or None when empty."""
    return (
        db.query(func.max(UploadHistory.id))
        .select_from(UploadHistory)
        .filter(UploadHistory.status.in_(["success", "partial"]))
        .scalar()
    )


def _apply_customer_search_filters(
    query: Query,
    *,
    customer_id: str | None,
    pan: str | None,
    acct_key: str | None,
    bank_type: str | None,
    occup_status_cd: str | None,
    income_min: int | None,
    income_max: int | None,
    rpt_dt_from: str | None,
    rpt_dt_to: str | None,
) -> Query:
    """Apply shared dynamic filters for customer search/export."""
    if customer_id:
        query = query.filter(MainData.customer_id == customer_id)
    if pan:
        query = query.filter(IdentityData.pan == pan)
    if acct_key:
        query = query.filter(MainData.acct_key == acct_key)
    if bank_type:
        query = query.filter(MainData.bank_type == bank_type)
    if occup_status_cd:
        query = query.filter(MainData.occup_status_cd == occup_status_cd)
    if income_min is not None:
        query = query.filter(cast(MainData.income, Integer) >= income_min)
    if income_max is not None:
        query = query.filter(cast(MainData.income, Integer) <= income_max)
    if rpt_dt_from:
        query = query.filter(MainData.rpt_dt >= rpt_dt_from)
    if rpt_dt_to:
        query = query.filter(MainData.rpt_dt <= rpt_dt_to)
    return query


def get_income_trend(db: Session, customer_id: str) -> list[ChartPoint]:
    """Return chart-ready income time series for a customer across all snapshots."""
    rows: Sequence[tuple] = (
        db.query(
            MainData.rpt_dt,
            MainData.snapshot_id,
            MainData.income,
        )
        .filter(MainData.customer_id == customer_id)
        .order_by(_rpt_dt_sort_key().asc(), MainData.snapshot_id.asc())
        .all()
    )

    points: list[ChartPoint] = []
    last_x: str | None = None
    last_y: int | float | None = None
    for rpt_dt, _snapshot_id, income in rows:
        if rpt_dt is None or rpt_dt == "":
            continue
        parsed = _parse_income(income)
        if parsed is None:
            continue
        if last_x == rpt_dt and last_y == parsed:
            continue
        points.append(ChartPoint(x=rpt_dt, y=parsed))
        last_x = rpt_dt
        last_y = parsed
    return points


def get_bank_trend(db: Session, customer_id: str) -> list[ChartPoint]:
    """Return chart-ready bank_type changes over time for a customer."""
    rows: Sequence[tuple] = (
        db.query(
            MainData.rpt_dt,
            MainData.snapshot_id,
            MainData.bank_type,
        )
        .filter(MainData.customer_id == customer_id)
        .order_by(_rpt_dt_sort_key().asc(), MainData.snapshot_id.asc())
        .all()
    )

    points: list[ChartPoint] = []
    last_bank_type: str | None = None
    for rpt_dt, _snapshot_id, bank_type in rows:
        if rpt_dt is None or rpt_dt == "":
            continue
        if bank_type is None or bank_type == "":
            continue
        if last_bank_type == bank_type:
            continue
        points.append(ChartPoint(x=rpt_dt, y=bank_type))
        last_bank_type = bank_type
    return points


# ---------------------------------------------------------------------------
# Global (aggregated) chart data — Section 3.5 "filter charts by global filters"
# ---------------------------------------------------------------------------


def get_global_income_trend(
    db: Session,
    *,
    bank_type: str | None = None,
    occup_status_cd: str | None = None,
    income_min: int | None = None,
    income_max: int | None = None,
    rpt_dt_from: str | None = None,
    rpt_dt_to: str | None = None,
) -> list[ChartPoint]:
    """Return average income grouped by RPT_DT across all customers in the latest snapshot.

    Accepts the same global filters as the search endpoint so the frontend
    can apply filters and see the chart update accordingly.
    """
    latest_snapshot = _get_latest_snapshot_id(db)
    if latest_snapshot is None:
        return []

    # Base query: average income per report date across the latest snapshot.
    query = (
        db.query(
            MainData.rpt_dt,
            func.round(func.avg(cast(MainData.income, Integer)), 2).label("avg_income"),
        )
        .filter(
            MainData.snapshot_id == latest_snapshot,
            MainData.income.isnot(None),
            MainData.income != "",
            MainData.rpt_dt.isnot(None),
            MainData.rpt_dt != "",
        )
    )

    # Apply the same filters the search/export endpoints use (minus customer_id,
    # pan, acct_key which are per-customer identifiers, not global filters).
    if bank_type:
        query = query.filter(MainData.bank_type == bank_type)
    if occup_status_cd:
        query = query.filter(MainData.occup_status_cd == occup_status_cd)
    if income_min is not None:
        query = query.filter(cast(MainData.income, Integer) >= income_min)
    if income_max is not None:
        query = query.filter(cast(MainData.income, Integer) <= income_max)
    if rpt_dt_from:
        query = query.filter(MainData.rpt_dt >= rpt_dt_from)
    if rpt_dt_to:
        query = query.filter(MainData.rpt_dt <= rpt_dt_to)

    rows = (
        query
        .group_by(MainData.rpt_dt)
        .order_by(_rpt_dt_sort_key().asc())
        .all()
    )

    return [
        ChartPoint(x=rpt_dt, y=float(avg_income))
        for rpt_dt, avg_income in rows
        if avg_income is not None
    ]


def get_global_bank_distribution(
    db: Session,
    *,
    occup_status_cd: str | None = None,
    income_min: int | None = None,
    income_max: int | None = None,
    rpt_dt_from: str | None = None,
    rpt_dt_to: str | None = None,
) -> list[ChartPoint]:
    """Return bank_type distribution (count per type) across the latest snapshot.

    Useful for a pie/bar chart showing how many records fall under each
    bank type, with optional global filters applied.
    """
    latest_snapshot = _get_latest_snapshot_id(db)
    if latest_snapshot is None:
        return []

    query = (
        db.query(
            MainData.bank_type,
            func.count(MainData.id).label("count"),
        )
        .filter(
            MainData.snapshot_id == latest_snapshot,
            MainData.bank_type.isnot(None),
            MainData.bank_type != "",
        )
    )

    # Apply global filters.
    if occup_status_cd:
        query = query.filter(MainData.occup_status_cd == occup_status_cd)
    if income_min is not None:
        query = query.filter(cast(MainData.income, Integer) >= income_min)
    if income_max is not None:
        query = query.filter(cast(MainData.income, Integer) <= income_max)
    if rpt_dt_from:
        query = query.filter(MainData.rpt_dt >= rpt_dt_from)
    if rpt_dt_to:
        query = query.filter(MainData.rpt_dt <= rpt_dt_to)

    rows = (
        query
        .group_by(MainData.bank_type)
        .order_by(func.count(MainData.id).desc())
        .all()
    )

    return [
        ChartPoint(x=bank_type, y=count)
        for bank_type, count in rows
    ]


def search_customers(
    db: Session,
    customer_id: str | None,
    pan: str | None,
    acct_key: str | None,
    bank_type: str | None,
    occup_status_cd: str | None,
    income_min: int | None,
    income_max: int | None,
    rpt_dt_from: str | None,
    rpt_dt_to: str | None,
    last_customer_id: str | None,
    page: int,
    page_size: int,
) -> CustomerSearchPage:
    """Search customers across main and identity data using the latest snapshot only.

    Supports both legacy OFFSET pagination (via `page`) and high-performance keyset
    pagination (via `last_customer_id`). When `last_customer_id` is provided, it
    takes precedence and keyset pagination is used.
    """
    latest_snapshot = _get_latest_snapshot_id(db)
    if latest_snapshot is None:
        return CustomerSearchPage(data=[], next_cursor=None)

    query = (
        db.query(
            MainData.customer_id,
            MainData.acct_key,
            MainData.bank_type,
            MainData.income,
            MainData.rpt_dt,
            IdentityData.pan,
        )
        .outerjoin(
            IdentityData,
            (MainData.customer_id == IdentityData.customer_id)
            & (MainData.snapshot_id == IdentityData.snapshot_id),
        )
        .filter(MainData.snapshot_id == latest_snapshot)
    )

    # Dynamic filters leveraging indexed columns (shared with export).
    query = _apply_customer_search_filters(
        query,
        customer_id=customer_id,
        pan=pan,
        acct_key=acct_key,
        bank_type=bank_type,
        occup_status_cd=occup_status_cd,
        income_min=income_min,
        income_max=income_max,
        rpt_dt_from=rpt_dt_from,
        rpt_dt_to=rpt_dt_to,
    )

    # Keyset pagination when last_customer_id is provided, otherwise keep legacy OFFSET
    if last_customer_id is not None:
        query = query.filter(MainData.customer_id > last_customer_id)
        rows: Sequence[tuple] = (
            query.order_by(MainData.customer_id).limit(page_size).all()
        )
    else:
        offset = (page - 1) * page_size
        rows = (
            query.order_by(MainData.customer_id)
            .offset(offset)
            .limit(page_size)
            .all()
        )

    data = [
        CustomerSearchResponse(
            customer_id=row[0],
            acct_key=row[1],
            bank_type=row[2],
            income=row[3],
            rpt_dt=row[4],
            pan=mask_pan(row[5]),
        )
        for row in rows
    ]

    next_cursor = rows[-1][0] if rows else None

    return CustomerSearchPage(data=data, next_cursor=next_cursor)


def get_customer_details(db: Session, customer_id: str) -> list[CustomerDetailResponse]:
    """Return all joined main + identity records for a specific customer."""
    query = (
        db.query(MainData, IdentityData)
        .outerjoin(
            IdentityData,
            (MainData.customer_id == IdentityData.customer_id)
            & (MainData.snapshot_id == IdentityData.snapshot_id),
        )
        .filter(MainData.customer_id == customer_id)
    )

    rows = query.all()
    if not rows:
        return []

    results: list[CustomerDetailResponse] = []
    for main_row, identity_row in rows:
        main_payload = MainDataResponse.model_validate(main_row)
        identity_payload = (
            IdentityDataResponse.model_validate(identity_row)
            if identity_row is not None
            else None
        )
        if identity_payload is not None:
            # After validation: mask sensitive identity fields before returning response.
            _apply_identity_masking(identity_payload)
        results.append(
            CustomerDetailResponse(
                main_data=main_payload,
                identity_data=identity_payload,
            )
        )

    return results


def get_upload_history(
    db: Session, *, limit: int = 50, offset: int = 0
) -> list[UploadHistoryResponse]:
    """Return upload history rows ordered by uploaded_at descending with pagination."""
    rows = (
        db.query(UploadHistory)
        .order_by(UploadHistory.uploaded_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [UploadHistoryResponse.model_validate(row) for row in rows]


def get_customer_timeline(db: Session, customer_id: str) -> CustomerTimelineResponse:
    """Return full historical timeline of a customer across all snapshots.

    Uses a column-based LEFT JOIN (outerjoin) and selects only required fields.
    Returns an empty timeline when no rows exist for the provided customer_id.

    Ordering is deterministic and stable:
    - Primary: rpt_dt ASC (NULL/empty pushed last)
    - Secondary: snapshot_id ASC
    """
    rpt_dt_sort_key = _rpt_dt_sort_key()

    rows: Sequence[tuple] = (
        db.query(
            MainData.snapshot_id,
            UploadHistory.uploaded_at,
            MainData.rpt_dt,
            MainData.income,
            MainData.bank_type,
            MainData.occup_status_cd,
            IdentityData.pan,
            IdentityData.passport,
            IdentityData.voter_id,
            IdentityData.uid,
            IdentityData.driving_license,
            IdentityData.ration_card,
        )
        .join(UploadHistory, MainData.snapshot_id == UploadHistory.id)
        .outerjoin(
            IdentityData,
            (MainData.customer_id == IdentityData.customer_id)
            & (MainData.snapshot_id == IdentityData.snapshot_id),
        )
        .filter(MainData.customer_id == customer_id)
        .order_by(rpt_dt_sort_key.asc(), MainData.snapshot_id.asc())
        .all()
    )

    timeline: list[CustomerTimelineEntry] = []
    for row in rows:
        entry = CustomerTimelineEntry(
            snapshot_id=row[0],
            uploaded_at=row[1],
            rpt_dt=row[2],
            income=row[3],
            bank_type=row[4],
            occup_status_cd=row[5],
            pan=row[6],
            passport=row[7],
            voter_id=row[8],
            uid=row[9],
            driving_license=row[10],
            ration_card=row[11],
        )
        # After validation: mask sensitive identity fields before returning response.
        _apply_identity_masking(entry)
        timeline.append(entry)

    return CustomerTimelineResponse(customer_id=customer_id, timeline=timeline)


def iter_customers_for_export(
    db: Session,
    customer_id: str | None,
    pan: str | None,
    acct_key: str | None,
    bank_type: str | None,
    occup_status_cd: str | None,
    income_min: int | None,
    income_max: int | None,
    rpt_dt_from: str | None,
    rpt_dt_to: str | None,
) -> Generator[tuple[MainData, IdentityData | None], None, None]:
    """Yield main + identity rows for all customers matching filters on latest snapshot.

    This reuses the same dynamic filters as the search API but intentionally does not
    apply pagination so the full filtered dataset can be streamed to the client.
    """
    latest_snapshot = _get_latest_snapshot_id(db)
    if latest_snapshot is None:
        return

    query: Query = (
        db.query(MainData, IdentityData)
        .outerjoin(
            IdentityData,
            (MainData.customer_id == IdentityData.customer_id)
            & (MainData.snapshot_id == IdentityData.snapshot_id),
        )
        .filter(MainData.snapshot_id == latest_snapshot)
    )

    query = _apply_customer_search_filters(
        query,
        customer_id=customer_id,
        pan=pan,
        acct_key=acct_key,
        bank_type=bank_type,
        occup_status_cd=occup_status_cd,
        income_min=income_min,
        income_max=income_max,
        rpt_dt_from=rpt_dt_from,
        rpt_dt_to=rpt_dt_to,
    )

    for main_row, identity_row in query.order_by(MainData.customer_id).yield_per(1000):
        # Mask identity fields before yielding any identity data out of the service.
        if identity_row is not None:
            # Use the same masking helpers as other services.
            identity_row.pan = mask_pan(identity_row.pan)
            identity_row.passport = mask_passport(identity_row.passport)
            identity_row.voter_id = mask_generic(
                identity_row.voter_id, keep_start=2, keep_end=2
            )
            identity_row.uid = mask_generic(
                identity_row.uid, keep_start=0, keep_end=4
            )
            identity_row.driving_license = mask_driving_license(
                identity_row.driving_license
            )
            identity_row.ration_card = mask_generic(
                identity_row.ration_card, keep_start=2, keep_end=2
            )
        yield main_row, identity_row


def stream_customers_csv(
    db: Session,
    customer_id: str | None,
    pan: str | None,
    acct_key: str | None,
    bank_type: str | None,
    occup_status_cd: str | None,
    income_min: int | None,
    income_max: int | None,
    rpt_dt_from: str | None,
    rpt_dt_to: str | None,
) -> Generator[str, None, None]:
    """Yield CSV chunks for all customers matching filters on latest snapshot."""
    import csv
    import io

    fieldnames = [
        "customer_id",
        "acct_key",
        "bank_type",
        "income",
        "income_freq",
        "occup_status_cd",
        "rpt_dt",
        "snapshot_id",
        "pan",
        "passport",
        "voter_id",
        "uid",
        "ration_card",
        "driving_license",
    ]

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)

    # Header row
    writer.writeheader()
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)

    for main_row, identity_row in iter_customers_for_export(
        db=db,
        customer_id=customer_id,
        pan=pan,
        acct_key=acct_key,
        bank_type=bank_type,
        occup_status_cd=occup_status_cd,
        income_min=income_min,
        income_max=income_max,
        rpt_dt_from=rpt_dt_from,
        rpt_dt_to=rpt_dt_to,
    ):
        row = {
            "customer_id": main_row.customer_id,
            "acct_key": main_row.acct_key,
            "bank_type": main_row.bank_type,
            "income": main_row.income,
            "income_freq": main_row.income_freq,
            "occup_status_cd": main_row.occup_status_cd,
            "rpt_dt": main_row.rpt_dt,
            "snapshot_id": main_row.snapshot_id,
            "pan": getattr(identity_row, "pan", None) if identity_row else None,
            "passport": getattr(identity_row, "passport", None)
            if identity_row
            else None,
            "voter_id": getattr(identity_row, "voter_id", None)
            if identity_row
            else None,
            "uid": getattr(identity_row, "uid", None) if identity_row else None,
            "ration_card": getattr(identity_row, "ration_card", None)
            if identity_row
            else None,
            "driving_license": getattr(identity_row, "driving_license", None)
            if identity_row
            else None,
        }
        writer.writerow(row)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


def get_customer_report_data(db: Session, customer_id: str) -> dict:
    """Return a structured, PDF-friendly representation of a customer.

    This reuses existing read-optimized helpers and avoids returning ORM objects.
    """
    details = get_customer_details(db, customer_id)
    timeline_response = get_customer_timeline(db, customer_id)

    if not details:
        return {
            "overview": {"customer_id": customer_id},
            "accounts": [],
            "identity": {},
            "timeline": [],
        }

    # Latest snapshot for overview (by rpt_dt then snapshot_id).
    latest_detail = max(details, key=_detail_sort_key)
    latest_main = latest_detail.main_data

    overview = {
        "customer_id": latest_main.customer_id,
        "primary_acct_key": latest_main.acct_key,
        "bank_type": latest_main.bank_type,
        "income": latest_main.income,
        "rpt_dt": latest_main.rpt_dt,
    }

    # Latest non-null identity: latest across snapshots with any populated field.
    latest_identity = _get_latest_non_null_identity(details)

    identity: dict[str, object] = {}
    if latest_identity is not None:
        identity = {
            "pan": latest_identity.pan,
            "uid": latest_identity.uid,
            "passport": latest_identity.passport,
            "voter_id": latest_identity.voter_id,
            "driving_license": latest_identity.driving_license,
            "ration_card": latest_identity.ration_card,
        }

    accounts: list[dict[str, object]] = []
    for item in details:
        md = item.main_data
        accounts.append(
            {
                "acct_key": md.acct_key,
                "bank_type": md.bank_type,
                "income": md.income,
                "income_freq": md.income_freq,
                "occup_status_cd": md.occup_status_cd,
                "rpt_dt": md.rpt_dt,
                "snapshot_id": md.snapshot_id,
            }
        )

    timeline: list[dict[str, object]] = []
    for entry in timeline_response.timeline:
        timeline.append(
            {
                "snapshot_id": entry.snapshot_id,
                "uploaded_at": entry.uploaded_at,
                "rpt_dt": entry.rpt_dt,
                "income": entry.income,
                "bank_type": entry.bank_type,
                "occup_status_cd": entry.occup_status_cd,
                "pan": entry.pan,
                "passport": entry.passport,
                "voter_id": entry.voter_id,
                "uid": entry.uid,
                "driving_license": entry.driving_license,
                "ration_card": entry.ration_card,
            }
        )

    return {
        "overview": overview,
        "accounts": accounts,
        "identity": identity,
        "timeline": timeline,
    }
