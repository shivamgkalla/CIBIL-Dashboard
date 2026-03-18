# Edge Cases and Handling

## Overview

The system processes upstream CIBIL data that is often messy, incomplete, or inconsistent. This document catalogs every edge case the codebase handles and the strategy used.

---

## 1. Missing or Invalid Income

### Where it matters

- Upload ingestion
- Customer search (income filtering)
- Summary analytics (income analysis)
- Timeline/trend charts
- PDF reports

### How it's handled

**Parsing** (`_parse_income` in `customer_service.py`):

```python
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
```

| Input | Result |
|-------|--------|
| `None` | `None` |
| `""` | `None` |
| `"  "` | `None` |
| `"75000"` | `75000` (int) |
| `"75,000"` | `75000` (int) |
| `"75000.50"` | `75000.5` (float) |
| `"N/A"` | `None` |
| `'""'` | `None` (after comma removal, empty string) |

**In analytics**: The income cache stores `None` for unparseable values. All analytics functions (`_build_income_analysis`, `_build_profile`) filter out `None` before computing:

```python
parsed_incomes = [v for v in income_cache_by_idx if v is not None]
if not parsed_incomes:
    return income_analysis  # defaults
```

**In search**: Income filtering casts to Integer at the SQL level:
```python
query = query.filter(cast(MainData.income, Integer) >= income_min)
```
Non-numeric income values will cause the cast to fail at the database level, effectively excluding those rows from filtered results.

**In trend charts**: Unparseable incomes are silently skipped — no data point is emitted.

**In PDF**: Income is rendered as-is from the raw data. No parsing or formatting is applied in the PDF service.

---

## 2. Invalid or Missing Dates

### Where it matters

- Sorting (detail views, timeline)
- Timeline insights (span, activity status)
- Trend charts (x-axis)
- Search filtering (date range)

### How it's handled

**Parsing** (`_safe_parse_rpt_dt` in `customer_service.py`):

```python
def _safe_parse_rpt_dt(value: object | None) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = parse(raw)  # dateutil.parser.parse
        return parsed.replace(tzinfo=None)
    except Exception:
        return None
```

`dateutil.parser.parse` handles many date formats automatically:
- `"2025-01-31"` — ISO format
- `"31/01/2025"` — DD/MM/YYYY
- `"Jan 31, 2025"` — Text format

Invalid dates return `None` without raising.

**In sorting** (`_detail_sort_key`):

```python
dt = _safe_parse_rpt_dt(main.rpt_dt) or datetime.min
snapshot_id = main.snapshot_id if main.snapshot_id is not None else 0
```

Records with unparseable dates sort first (using `datetime.min`), ensuring they don't disrupt the ordering of valid records.

**In SQL sorting** (`_rpt_dt_sort_key`):

```python
case(
    (MainData.rpt_dt.is_(None), literal("9999-12-31")),
    (MainData.rpt_dt == "", literal("9999-12-31")),
    else_=MainData.rpt_dt,
)
```

NULL/empty `rpt_dt` values are pushed to the END in SQL queries (sorted as "9999-12-31"). This is the opposite of the Python sort (which uses `datetime.min`), because:
- SQL sorting is used for timeline display (latest last, unknowns last)
- Python sorting is used for finding "first" and "latest" records (unknowns first, so they don't claim "latest")

**In timeline insights**:

```python
rpt_dates = [d for d in parsed_rpt_dt if d is not None]
if not rpt_dates:
    return timeline_insights  # defaults
```

Invalid dates are excluded from span and activity calculations entirely.

**In trend charts**: Entries with NULL or empty `rpt_dt` are skipped:
```python
if rpt_dt is None or rpt_dt == "":
    continue
```

**In search filtering**: `rpt_dt_from` and `rpt_dt_to` use string comparison, which works correctly for YYYY-MM-DD format. The router validates that `rpt_dt_from <= rpt_dt_to`:
```python
if rpt_dt_from is not None and rpt_dt_to is not None and rpt_dt_from > rpt_dt_to:
    raise HTTPException(status_code=400, detail="rpt_dt_from cannot be greater than rpt_dt_to")
```

---

## 3. Single Snapshot

When a customer has data from only one upload (snapshot):

| Analytics Section | Behavior |
|-------------------|----------|
| Profile | Shows that single snapshot's values |
| Income Analysis | `avg = max = min = latest_income`, `trend = "stable"`, `volatility = "low"` (range=0) |
| Bank Analysis | 1 unique type, 0 changes |
| Timeline Insights | `total_snapshots = 1`, `reporting_span_days = 0` |
| Income Trend | 1 data point |
| Bank Trend | 1 data point (or 0 if bank_type is null) |

---

## 4. Empty Identity Data

### Where it matters

- Customer details
- Timeline
- Summary analytics (identity analysis)
- PDF reports
- CSV export

### How it's handled

**In customer details**: The LEFT JOIN ensures customers without identity records still appear:
```python
db.query(MainData, IdentityData).outerjoin(
    IdentityData,
    (MainData.customer_id == IdentityData.customer_id)
    & (MainData.snapshot_id == IdentityData.snapshot_id),
)
```

When `IdentityData` is NULL (no match), `identity_data` in the response is `null`.

**In identity analysis** (`_build_identity_analysis`):
```python
latest_identity = _get_latest_non_null_identity(sorted_details) if sorted_details else None
if latest_identity is None:
    return identity_analysis  # defaults
```

Returns: `identity_types_present: [], identity_count: 0, has_strong_identity: false, latest_identity: {}`

**In `_get_latest_non_null_identity`**:

```python
for item in sorted(details, key=_detail_sort_key, reverse=True):
    identity_model = item.identity_data
    if identity_model is None:
        continue
    if any([identity_model.pan, identity_model.uid, ...]):
        return identity_model
return None
```

This walks backwards through snapshots. An identity record that exists but has ALL empty fields is treated the same as a missing record — it's skipped.

**In PDF reports**: The identity section shows a dash (`"-"`) for both label and value when all identity fields are empty.

**In CSV export**: Identity columns are `None` → rendered as empty in the CSV.

---

## 5. Missing CUSTOMER_ID During Upload

```python
customer_id = (row.get("CUSTOMER_ID") or "").strip()
if not customer_id:
    records_failed += 1
    error_batch.append({
        "upload_id": snapshot_id,
        "row_number": row_number,
        "error_message": "Missing CUSTOMER_ID",
        "raw_data": _safe_raw_data(row),
    })
    continue
```

Rows without a CUSTOMER_ID are:
1. Counted as failures
2. Logged to `upload_errors` with the error message and truncated raw data
3. Skipped (never inserted into `main_data`)
4. Processing continues with the next row

---

## 6. Empty-String Normalization During Upload

```python
def _normalize_empty(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value or value == '""':
        return None
    return value
```

Handles:
- `None` → `None`
- `""` → `None`
- `"  "` (whitespace) → `None`
- `'""'` (quoted empty) → `None`
- `"PSU"` → `"PSU"` (preserved)

This normalizes inconsistent empty representations from upstream files.

---

## 7. No Upload Data (Empty Database)

### Search

```python
latest_snapshot = _get_latest_snapshot_id(db)
if latest_snapshot is None:
    return CustomerSearchPage(data=[], next_cursor=None)
```

Returns an empty result set, not an error.

### Dashboard

```python
if latest_snapshot is None:
    empty_summary = DashboardSummary(
        total_customers=0, total_records=0, latest_upload_date=None, average_income=0
    )
    return DashboardResponse(summary=empty_summary, bank_distribution=[], recent_uploads=[])
```

Returns a well-formed but empty dashboard payload.

### CSV Export

```python
def iter_customers_for_export(...):
    latest_snapshot = _get_latest_snapshot_id(db)
    if latest_snapshot is None:
        return  # generator yields nothing
```

The CSV export yields only the header row (no data rows).

---

## 8. Large Datasets

```python
if len(details) > 5000:
    log.warning(
        "Large dataset for customer",
        extra={"customer_id": customer_id, "details_count": len(details)},
    )
```

Customers with more than 5000 records trigger a warning log. No special handling is applied — the analytics compute normally — but the warning helps identify potential performance issues.

---

## 9. Bulk Insert Failures

```python
try:
    with db.begin_nested():
        db.bulk_insert_mappings(MainData, main_batch)
        db.bulk_insert_mappings(IdentityData, identity_batch)
        db.flush()
        records_inserted += len(main_batch)
except Exception as e:
    failed_rows = len(main_batch)
    # Log error rows
    for row_number, raw in zip(main_batch_row_numbers, main_batch, strict=False):
        error_batch.append({...})
```

When a batch insert fails:
1. The savepoint rolls back (only this batch, not previous ones)
2. Each row in the failed batch is recorded as an `UploadError`
3. The error batch is flushed in a separate nested transaction
4. Processing continues with the next batch

If even the error recording fails:
```python
except Exception:
    logger.exception("Failed to persist upload error rows for snapshot_id=%s", snapshot_id)
```
The error is logged but processing continues.

---

## 10. Upload Status Determination

```python
status = UploadStatus.SUCCESS
if records_failed and records_inserted:
    status = UploadStatus.PARTIAL
elif records_failed and not records_inserted:
    status = UploadStatus.FAILED
```

| Inserted | Failed | Status |
|----------|--------|--------|
| > 0 | 0 | `success` |
| > 0 | > 0 | `partial` |
| 0 | > 0 | `failed` |
| 0 | 0 | `success` (empty file) |

---

## 11. Masking Short Values

```python
if n <= 1:
    return mask_char * n      # Single char → "*"

if ks + ke >= n:
    return (mask_char * (n - 1)) + raw[-1]  # Keep only last char
```

| Input | keep_start | keep_end | Result |
|-------|-----------|----------|--------|
| `"A"` | any | any | `"*"` |
| `"AB"` | 5 | 1 | `"*B"` (keep_start + keep_end > length) |
| `None` | any | any | `None` |
| `""` | any | any | `""` (preserved as-is) |
| `"  "` | any | any | `"  "` (whitespace preserved) |

---

## 12. Audit Log Failures

```python
try:
    with db.begin_nested():
        log_customer_view(db=db, user_id=current_user.id, customer_id=customer_id)
    db.commit()
except Exception:
    db.rollback()
```

If audit logging fails (database error, constraint violation, etc.):
- The savepoint is rolled back
- The customer data response is still returned normally
- The error is silently swallowed (no logging of the audit failure itself)

This is a deliberate trade-off: audit logging should never break the core functionality.

---

## 13. File Extension Validation

```python
def _validate_txt_file(file: UploadFile, field_name: str) -> None:
    filename = file.filename or ""
    if not filename.lower().endswith(".txt"):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a .txt file")
```

Only `.txt` files are accepted. The check is case-insensitive. If the file has no filename (e.g., programmatic upload), it defaults to an empty string which fails the `.txt` check.

---

## 14. Raw Data Truncation in Error Records

```python
RAW_DATA_MAX_CHARS = 1000

def _safe_raw_data(value: object) -> str:
    try:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        try:
            serialized = repr(value)
        except Exception:
            serialized = "<unserializable>"
    try:
        return serialized[:RAW_DATA_MAX_CHARS]
    except Exception:
        return ""
```

Multi-layer fallback:
1. Try `json.dumps` (handles most dict/list data)
2. Try `repr` (handles objects)
3. Use `"<unserializable>"` (handles everything else)
4. Truncate to 1000 chars (prevents DB bloat)
5. If even truncation fails, return empty string

---

## 15. Concurrent Password Reset Tokens

When a user requests multiple password resets before using any:

```python
db.query(PasswordResetToken)
    .filter(PasswordResetToken.user_id == user.id, PasswordResetToken.used.is_(False))
    .update({PasswordResetToken.used: True}, synchronize_session="fetch")
```

On successful reset, ALL unused tokens for that user are invalidated, not just the one used. This prevents stale tokens from remaining valid.

---

## 16. Income Range Validation in Search

```python
if income_min is not None and income_max is not None and income_min > income_max:
    raise HTTPException(status_code=400, detail="income_min cannot be greater than income_max")
```

The router validates that `income_min <= income_max` before reaching the service layer. Same validation applies to date ranges. This prevents nonsensical queries from reaching the database.

---

## 17. User Self-Modification Protection

The admin user management service has three self-protection checks:

1. **Cannot delete yourself**: Prevents admin lockout
2. **Cannot demote yourself**: Prevents accidental loss of admin access
3. **Unique username/email enforcement**: Explicit queries + HTTP 400 rather than relying on DB constraint errors

Each is enforced at the service layer with clear error messages.
