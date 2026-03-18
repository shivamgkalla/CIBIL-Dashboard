# Service Layer Explained

## Overview

The service layer is the core of the application. It sits between routers and the database, containing all business logic, data transformations, analytics computations, and masking enforcement. There are **10 service modules**, each responsible for a distinct domain.

---

## 1. `customer_service.py` — The Central Service (~1000 lines)

**File**: `app/services/customer_service.py`

This is the largest and most critical service. It handles customer search, detail retrieval, timeline construction, analytics summary, trend data, CSV export, and report data preparation.

### Key Functions

#### `search_customers()`

**Purpose**: Search customers across the latest snapshot with optional filters and pagination.

**How it works**:
1. Fetches the latest `snapshot_id` via `_get_latest_snapshot_id()` (queries `MAX(UploadHistory.id)`)
2. Builds a query: `MainData OUTER JOIN IdentityData` filtered to the latest snapshot
3. Applies dynamic filters via `_apply_customer_search_filters()` — a shared filter function also used by CSV export
4. Applies pagination:
   - If `last_customer_id` is provided → **keyset pagination** (`WHERE customer_id > cursor ORDER BY customer_id LIMIT N`)
   - Otherwise → **offset pagination** (`OFFSET (page-1)*page_size LIMIT page_size`)
5. Maps results to `CustomerSearchResponse`, masking PAN via `mask_pan()`
6. Returns `CustomerSearchPage` with a `next_cursor` for the next page

**Design decision**: Keyset pagination was added for performance on large datasets. Offset pagination remains for backward compatibility with frontends that use page numbers.

#### `get_customer_details()`

**Purpose**: Return all joined main + identity records for a specific customer across ALL snapshots.

**How it works**:
1. Queries `MainData LEFT JOIN IdentityData` on `(customer_id, snapshot_id)`
2. Filters by the provided `customer_id`
3. For each row:
   - Validates `MainData` → `MainDataResponse` via `model_validate`
   - Validates `IdentityData` → `IdentityDataResponse` (if present)
   - Applies `_apply_identity_masking()` to the identity response object
4. Returns a list of `CustomerDetailResponse`

**Key point**: Unlike search, this returns data from ALL snapshots, not just the latest. This is intentional — it powers the detailed view where you want to see every record across time.

#### `get_customer_timeline()`

**Purpose**: Return a time-ordered history of a customer's data across all snapshots.

**How it works**:
1. Builds a three-table join:
   - `MainData JOIN UploadHistory` on `snapshot_id` (to get `uploaded_at`)
   - `LEFT JOIN IdentityData` on `(customer_id, snapshot_id)`
2. Filters by `customer_id`
3. Orders by `rpt_dt ASC` (with NULL/empty pushed last via `_rpt_dt_sort_key()`) then `snapshot_id ASC`
4. Maps each row to `CustomerTimelineEntry` and applies `_apply_identity_masking()`
5. Returns `CustomerTimelineResponse`

**The sorting CASE expression** (`_rpt_dt_sort_key()`):
```python
case(
    (MainData.rpt_dt.is_(None), literal("9999-12-31")),
    (MainData.rpt_dt == "", literal("9999-12-31")),
    else_=MainData.rpt_dt,
)
```
This pushes NULL or empty `rpt_dt` values to the end of the sorted result, ensuring deterministic ordering even when date data is missing.

#### `get_customer_summary_analytics()`

**Purpose**: Generate analytical insights for a customer. Documented in detail in [ANALYTICS_ENGINE.md](./ANALYTICS_ENGINE.md).

#### `get_income_trend()` / `get_bank_trend()`

**Purpose**: Return chart-ready time series data.

**Income trend**:
- Queries `(rpt_dt, snapshot_id, income)` ordered by `rpt_dt ASC, snapshot_id ASC`
- Parses income via `_parse_income()`, skipping unparseable values
- Deduplicates consecutive identical `(x, y)` pairs to reduce noise
- Returns `list[ChartPoint]`

**Bank trend**:
- Same ordering but tracks bank_type changes
- Only emits a point when `bank_type` differs from the previous entry
- Filters out NULL/empty values

#### `stream_customers_csv()`

**Purpose**: Generate CSV rows as a stream for memory-efficient export.

**How it works**:
1. Yields a CSV header row first
2. Calls `iter_customers_for_export()` which:
   - Uses the same filters as search (via `_apply_customer_search_filters()`)
   - Queries latest snapshot only
   - Uses `yield_per(1000)` for database-level streaming (only 1000 ORM objects in memory at a time)
   - Masks identity fields before yielding each row
3. Each data row is written to a `StringIO` buffer, yielded as a string, then the buffer is cleared

**Design decision**: The `StringIO` buffer is reused per row rather than creating a new one each time, reducing GC pressure during large exports.

#### `get_customer_report_data()`

**Purpose**: Prepare a flat dict structure suitable for PDF generation.

**How it works**:
1. Calls `get_customer_details()` and `get_customer_timeline()`
2. Finds the latest record using `max(details, key=_detail_sort_key)`
3. Extracts overview fields from the latest record
4. Finds the latest non-null identity via `_get_latest_non_null_identity()`
5. Returns a dict with four sections: `overview`, `accounts`, `identity`, `timeline`

### Important Helper Functions

#### `_apply_identity_masking(obj)`

Central masking function. Operates on **Pydantic response objects** (never DB rows). Masks six fields using `setattr`:

| Field | Masking Function | Visible Portion |
|-------|-----------------|-----------------|
| `pan` | `mask_pan()` | First 5 + last 1 (e.g., `ABCDE****F`) |
| `uid` | `mask_generic(keep_start=0, keep_end=4)` | Last 4 (e.g., `********9012`) |
| `passport` | `mask_passport()` | First 2 + last 2 |
| `driving_license` | `mask_driving_license()` | First 2 + last 4 |
| `voter_id` | `mask_generic(keep_start=2, keep_end=2)` | First 2 + last 2 |
| `ration_card` | `mask_generic(keep_start=2, keep_end=2)` | First 2 + last 2 |

Each masking operation is wrapped in `try/except` to ensure a single field failure never crashes the response.

#### `_parse_income(value)`

Robust income parser that handles:
- `None` → `None`
- Empty string → `None`
- Comma-separated numbers (`"75,000"` → `75000`)
- Integers and floats
- Non-numeric strings → `None` (no exception raised)

#### `_safe_parse_rpt_dt(value)`

Date parser using `dateutil.parser.parse()`. Handles:
- `None` / empty → `None`
- Various date formats → `datetime` (with timezone stripped for consistency)
- Invalid formats → `None`

#### `_detail_sort_key(item)`

Deterministic ordering key: `(rpt_dt as datetime, snapshot_id as int)`. When `rpt_dt` is missing or unparseable, `datetime.min` is used. When `snapshot_id` is None, `0` is used.

#### `_get_latest_non_null_identity(details)`

Walks through details sorted by `_detail_sort_key` in reverse (latest first) and returns the first identity that has at least one non-empty field.

#### `_strip_none_values(value)`

Recursively removes `None` values from dicts and lists. Applied to the analytics summary response to avoid `null` pollution in the JSON output.

#### `_norm_str(value)`

Normalizes potentially-null values into stripped strings. `None` → `""`, otherwise `str(value).strip()`.

---

## 2. `upload_service.py` — File Ingestion (~300 lines)

**File**: `app/services/upload_service.py`

Handles the entire upload pipeline. See [DATA_FLOW.md](./DATA_FLOW.md) for the complete step-by-step.

### Key Functions

#### `process_upload_files()`

Orchestrates the full upload:
1. Creates `UploadHistory` record (committed early to get `snapshot_id`)
2. Builds identity map via `_build_identity_map()`
3. Iterates main file rows, buffering into batches
4. Flushes batches every 10,000 rows via `flush_batches()`
5. Updates history with final counts

#### `_build_identity_map()`

Reads the identity file into a `dict[str, dict[str, str]]` keyed by `CUSTOMER_ID`. Uses `csv.DictReader` with pipe delimiter.

#### `_iter_decoded_lines()`

Memory-efficient line-by-line decoder for `UploadFile`. Reads binary chunks from the `SpooledTemporaryFile` and decodes UTF-8 per line with `errors="replace"`.

#### `flush_batches()`

Nested function that performs bulk insert using `db.bulk_insert_mappings()`. Uses `db.begin_nested()` for savepoint safety — if a batch fails, only that batch is rolled back. Error rows are persisted to `upload_errors` with truncated raw data (max 1000 chars via `_safe_raw_data()`).

### Constants

- `BATCH_SIZE = 10_000` — rows accumulated before flushing
- `RAW_DATA_MAX_CHARS = 1000` — maximum length of raw data stored in error records

---

## 3. `auth_service.py` — Authentication

**File**: `app/services/auth_service.py`

### Key Functions

- `create_user()` — Creates a user with hashed password. Enforces role restrictions (only admin can create admin)
- `authenticate_user_with_reason()` — Returns `(user, failure_reason)` tuple. Failure reasons: `"user_not_found"` or `"invalid_credentials"`. Used for audit logging
- `generate_token()` — Creates a JWT with the user's ID, username, and role
- `get_user_by_id()` / `get_user_by_username()` — Simple lookup functions

---

## 4. `user_service.py` — Admin User Management

**File**: `app/services/user_service.py`

### Key Functions

- `create_user_admin()` — Creates a user with uniqueness checks (`_ensure_unique_username`, `_ensure_unique_email`). Enforces that only admins can assign admin role
- `update_user_admin()` — Partial update with field-level validation. Prevents admin self-demotion
- `delete_user_admin()` — Deletes a user. Prevents admin self-deletion
- `get_all_users()` — Returns all users ordered by `created_at DESC`

**Design decision**: Uniqueness checks use explicit queries + HTTP exceptions rather than relying on database-level unique constraint errors. This provides cleaner error messages to the client.

---

## 5. `dashboard_service.py` — Dashboard Analytics

**File**: `app/services/dashboard_service.py`

Single function: `get_dashboard_data()`.

Runs aggregate queries on the latest snapshot:
- `COUNT(DISTINCT customer_id)` — total customers
- `COUNT(id)` — total records
- `AVG(NULLIF(income, '') CAST Float)` — average income (handles empty strings)
- `GROUP BY bank_type, COUNT` — bank type distribution
- Latest 5 `UploadHistory` entries

All queries use raw SQL aggregation functions (no ORM object loading), keeping memory usage minimal even on million-row datasets.

---

## 6. `pdf_service.py` — PDF Generation

**File**: `app/services/pdf_service.py`

Single function: `generate_customer_pdf()`. Documented in detail in [PDF_REPORT_FLOW.md](./PDF_REPORT_FLOW.md).

---

## 7. `login_activity_service.py` — Login Audit

**File**: `app/services/login_activity_service.py`

Two functions:
- `log_login_attempt()` — Adds a `LoginActivity` record. Uses `db.flush()` without commit (caller controls transaction). Records IP address, user agent, success/failure, and failure reason
- `get_login_activity()` — Paginated query ordered by `login_time DESC`

---

## 8. `customer_view_activity_service.py` — View Audit

**File**: `app/services/customer_view_activity_service.py`

Two functions:
- `log_customer_view()` — Adds a `CustomerViewActivity` record. Uses `db.flush()` without commit
- `get_customer_view_activity()` — Paginated query ordered by `viewed_at DESC`

**Transaction pattern**: Both audit log functions only flush, never commit. The calling router wraps the audit log in a `begin_nested()` savepoint with a `try/except` to ensure that audit logging failures never break the main response:

```python
try:
    with db.begin_nested():
        log_customer_view(db=db, user_id=current_user.id, customer_id=customer_id)
    db.commit()
except Exception:
    db.rollback()
```

---

## 9. `password_reset_service.py` — Password Reset

**File**: `app/services/password_reset_service.py`

### Key Functions

- `generate_reset_token()` — Creates a 32-byte URL-safe random token via `secrets.token_urlsafe()`
- `create_reset_token()` — Persists SHA-256 hash of the token with 15-minute expiration
- `request_password_reset()` — Generates token, builds reset link. In DEBUG mode, prints the link to terminal. In production, placeholder for email integration
- `reset_password_with_token()` — Validates token (not used, not expired), updates password, and invalidates ALL unused tokens for that user (prevents token reuse across concurrent requests)

**Security decisions**:
- Raw token is never stored — only SHA-256 hash
- Response is identical whether email exists or not (prevents enumeration)
- All unused tokens for a user are invalidated on successful reset

---

## 10. `saved_filter_service.py` — Saved Filters

**File**: `app/services/saved_filter_service.py`

Three simple CRUD functions:
- `create_saved_filter()` — Creates a new `SavedFilter` record
- `get_saved_filters()` — Returns all filters for a user, ordered by `created_at DESC`
- `delete_saved_filter()` — Deletes by `(filter_id, user_id)` to enforce ownership. Returns 404 if not found or not owned by user

---

## Service Layer Design Principles

1. **Services own all business logic**: Routers are thin — they validate input, call a service, and format the HTTP response
2. **Services never return ORM objects to routers** (in most cases): They return Pydantic models or plain dicts
3. **Masking happens in services, never in routers or models**: The `_apply_identity_masking()` helper and explicit `mask_*()` calls ensure sensitive data is masked before leaving the service layer
4. **Transaction boundaries are service-controlled**: Most services commit their own transactions. Audit log services only flush, letting the caller control the commit boundary
5. **Shared logic is factored into private helpers**: `_apply_customer_search_filters()`, `_detail_sort_key()`, `_parse_income()`, etc. are used by multiple public functions within the same module
