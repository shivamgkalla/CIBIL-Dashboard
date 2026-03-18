# Analytics Engine

## Overview

The analytics engine is implemented in `app/services/customer_service.py`, primarily in the `get_customer_summary_analytics()` function and its five builder helpers. It computes real-time analytical insights for a customer by aggregating data across all snapshots.

## Entry Point

```python
def get_customer_summary_analytics(db: Session, customer_id: str) -> dict:
```

Called from `GET /customers/{customer_id}/summary` in the customer router.

---

## Architecture

The function follows a **gather → cache → compute → clean** pattern:

```
1. GATHER: Call get_customer_details() and get_customer_timeline()
2. SORT:   Sort details by _detail_sort_key (rpt_dt, snapshot_id)
3. CACHE:  Pre-parse income values and report dates into indexed caches
4. COMPUTE: Run five independent builder functions
5. CLEAN:  Strip None values from the result
```

### Why This Pattern?

Income parsing (`_parse_income()`) and date parsing (`_safe_parse_rpt_dt()`) are expensive when called repeatedly. By caching parsed values in indexed lists that mirror the sorted details/timeline arrays, each value is parsed exactly once. The builders then work from these caches.

---

## The Five Analytics Sections

### 1. Profile (`_build_profile`)

**What it computes**:

| Field | Logic |
|-------|-------|
| `total_accounts` | `len(sorted_details)` — count of all main data records across snapshots |
| `latest_income` | Parsed income from the last record (chronologically) |
| `latest_bank_type` | `bank_type` from the last record |
| `first_report_date` | `rpt_dt` from the first record |
| `latest_report_date` | `rpt_dt` from the last record |

**Edge cases**:
- Empty details list → returns all-zero/empty defaults
- Missing income on latest record → defaults to `0`
- Missing bank_type → defaults to empty string

### 2. Income Analysis (`_build_income_analysis`)

**What it computes**:

| Field | Logic |
|-------|-------|
| `avg_income` | Mean of all non-null parsed incomes, rounded to 2 decimal places |
| `max_income` | Maximum parsed income |
| `min_income` | Minimum parsed income |
| `trend` | Comparison of first vs last non-null income |
| `volatility` | Based on `(max - min) / avg` ratio |

**Trend determination**:
```
If < 2 valid income values → "stable"
If last_income > first_income → "increasing"
If last_income < first_income → "decreasing"
If last_income == first_income → "stable"
```

The first/last income are found by scanning the cached income list from the start and end respectively, skipping `None` values. This correctly handles cases where income is missing in early or late snapshots.

**Volatility thresholds** (defined as module-level constants):
```python
INCOME_VOLATILITY_LOW = 0.2      # range/avg < 0.2 → "low"
INCOME_VOLATILITY_MEDIUM = 0.5   # range/avg < 0.5 → "medium"
                                  # range/avg >= 0.5 → "high"
```

**Edge cases**:
- No valid incomes → returns defaults (all zeros, empty strings)
- Single valid income → trend is `"stable"`, volatility is `"low"` (range is 0)
- Zero average income → volatility is empty string (avoids division by zero)

### 3. Bank Analysis (`_build_bank_analysis`)

**What it computes**:

| Field | Logic |
|-------|-------|
| `unique_bank_types` | Sorted set of all bank types seen across timeline/details |
| `bank_type_change_count` | Number of times the bank type changed between consecutive entries |
| `most_frequent_bank_type` | Mode of bank types (via `Counter.most_common(1)`) |

**Data source preference**: The function first tries to extract bank types from the timeline entries (which are already chronologically ordered by the service query). If the timeline is empty, it falls back to sorted details.

**Change counting logic**:
```python
changes = 0
prev = None
for bt in bank_types:
    if prev is None:
        prev = bt
        continue
    if bt != prev:
        changes += 1
        prev = bt
```

This counts actual transitions, not unique values. For example, `[PSU, PVT, PSU]` = 2 changes.

**Edge cases**:
- No bank types found → returns defaults
- Single entry → 0 changes, that entry is the most frequent

### 4. Identity Analysis (`_build_identity_analysis`)

**What it computes**:

| Field | Logic |
|-------|-------|
| `identity_types_present` | Sorted list of identity field names that have values |
| `identity_count` | Count of present identity types |
| `has_strong_identity` | Boolean (see below) |
| `latest_identity` | Dict of non-empty identity fields (masked values) |

**Strong identity definition**:
```python
has_strong_identity = bool(
    identity_fields.get("pan")
    or identity_fields.get("uid")
    or (identity_fields.get("passport") and identity_fields.get("driving_license"))
)
```

A customer has "strong identity" if they have:
- PAN, **or**
- UID (Aadhaar), **or**
- Both passport AND driving license

This reflects Indian KYC norms where PAN or Aadhaar alone is sufficient for identity verification, while passport + DL together can substitute.

**Data source**: Uses `_get_latest_non_null_identity()` which walks through details in reverse chronological order and returns the first identity record that has at least one non-empty field. This means the analysis always reflects the most recent identity data available, even if some snapshots are missing identity records.

**Important**: Identity values used here are already **masked** (because they come from `get_customer_details()` which applies masking). The `latest_identity` dict contains masked values.

**Edge cases**:
- No identity data at all → returns defaults (empty list, count=0, false, empty dict)
- Identity with only empty fields → skipped, next snapshot checked
- All snapshots have empty identity → returns defaults

### 5. Timeline Insights (`_build_timeline_insights`)

**What it computes**:

| Field | Logic |
|-------|-------|
| `total_snapshots` | `len(timeline)` — number of timeline entries |
| `reporting_span_days` | Days between earliest and latest valid `rpt_dt` |
| `activity_status` | `"active"` if latest report within 365 days, else `"inactive"` |

**Activity threshold** (module-level constant):
```python
ACTIVE_DAYS_THRESHOLD = 365
```

**Span calculation**:
```python
first_dt = min(rpt_dates)
last_dt = max(rpt_dates)
reporting_span_days = max(0, (last_dt.date() - first_dt.date()).days)
```

**Activity status**:
```python
activity_status = (
    "active"
    if (datetime.utcnow().date() - last_dt.date()) <= timedelta(days=365)
    else "inactive"
)
```

**Edge cases**:
- No valid report dates → returns defaults (0 snapshots, 0 days, empty status)
- Single valid date → span is 0 days, activity depends on recency
- All dates unparseable → same as no valid dates

---

## Caching Strategy

### Income Cache

```python
income_cache_by_idx: list[int | float | None] = []
for item in sorted_details:
    raw_income = _norm_str(item.main_data.income)
    parsed = _parse_income(raw_income) if raw_income else None
    income_cache_by_idx.append(parsed)
```

This creates a 1:1 indexed mapping to `sorted_details`. Parse failures are counted and logged at DEBUG level.

### Report Date Cache

```python
rpt_dt_cache: list[datetime | None] = []
for entry in timeline:
    raw_rpt_dt = _norm_str(entry.rpt_dt)
    parsed_dt = _safe_parse_rpt_dt(raw_rpt_dt) if raw_rpt_dt else None
    rpt_dt_cache.append(parsed_dt)
```

Same pattern — indexed to `timeline` entries. Parse failures counted and logged at DEBUG level.

---

## Default Values

The `_default_summary_sections()` function provides a complete set of zero/empty defaults for all five sections. This ensures:
- The response always has the same shape, even when data is missing
- No `None` values leak into the response
- Frontend can always render without null checks

```python
{
    "profile": {"total_accounts": 0, "latest_income": 0, ...},
    "income_analysis": {"avg_income": 0, "max_income": 0, ...},
    "bank_analysis": {"unique_bank_types": [], ...},
    "identity_analysis": {"identity_types_present": [], ...},
    "timeline_insights": {"total_snapshots": 0, ...},
}
```

---

## Null Stripping

After all five sections are computed, the result passes through `_strip_none_values()`:

```python
def _strip_none_values(value):
    if isinstance(value, dict):
        cleaned = {}
        for k, v in value.items():
            if v is None:
                continue
            cv = _strip_none_values(v)
            cleaned[k] = cv
        return cleaned
    if isinstance(value, list):
        return [v for v in (_strip_none_values(x) for x in value) if v is not None]
    return value
```

This recursively removes any stray `None` values from nested dicts and lists, ensuring clean JSON output.

---

## Performance Characteristics

For a customer with `N` detail records and `M` timeline entries:
- Database: 2 queries (details + timeline)
- Income parsing: O(N) — exactly once per record
- Date parsing: O(M) — exactly once per timeline entry
- Sorting: O(N log N) for details
- Analytics: O(N + M) linear scans
- Total: **O(N log N + M)**, dominated by the sorting step

For large customers (>5000 records), a warning is logged:
```python
if len(details) > 5000:
    log.warning("Large dataset for customer", extra={...})
```

---

## Chart Trend Functions

### `get_income_trend()`

Returns `list[ChartPoint]` for charting income over time.

**Deduplication**: Consecutive identical `(rpt_dt, income)` pairs are suppressed to reduce noise in charts. For example, if the same income appears across multiple snapshots with the same report date, only one point is emitted.

### `get_bank_trend()`

Returns `list[ChartPoint]` for charting bank type changes.

**Change-only emission**: Only emits a point when the bank type changes from the previous entry. This makes the chart show actual transitions rather than every data point.

Both use the same `_rpt_dt_sort_key()` CASE expression for consistent ordering.
