# Database Schema

## Overview

The system uses **PostgreSQL** with **SQLAlchemy 2.0** mapped columns and **Alembic** for schema versioning. The database schema is never managed via `create_all()` — all changes go through migration scripts in `alembic/versions/`.

There are **9 tables** organized into three functional groups:

1. **Core Data** — `main_data`, `identity_data`
2. **Users & Auth** — `users`, `login_activity`, `password_reset_tokens`
3. **Audit & Features** — `upload_history`, `upload_errors`, `customer_view_activity`, `saved_filters`

---

## Core Data Tables

### `main_data`

**File**: `app/models/main_data_model.py`

Stores the core account-level CIBIL data for each snapshot row. Each row represents a single account entry from a single upload.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | Integer (PK) | No | Auto-increment primary key |
| `acct_key` | String(50) | Yes | Account key / facility identifier |
| `customer_id` | String(50) | Yes | Customer identifier from bureau file |
| `income` | Text | Yes | Reported income (stored as string — see note) |
| `income_freq` | String(10) | Yes | Income frequency code |
| `occup_status_cd` | String(10) | Yes | Occupation status code |
| `rpt_dt` | String(10) | Yes | Report date (stored as string, typically YYYY-MM-DD) |
| `bank_type` | String(10) | Yes | Bank type flag (PSU, PVT, NBF, HFC) |
| `snapshot_id` | Integer | Yes | Foreign key to `upload_history.id` — identifies which upload |
| `created_at` | DateTime(tz) | No | Row creation timestamp (server default) |

**Indexes**:
- `ix_main_data_customer_snapshot` — Composite on `(customer_id, snapshot_id)` for fast customer lookups within a snapshot
- `ix_main_data_occup_status_cd` — For filtering by occupation status
- `ix_main_data_rpt_dt` — For date range queries
- Individual indexes on `acct_key`, `customer_id`, `snapshot_id`

**Design decision — income as Text**: Income is stored as `Text` rather than a numeric type because the upstream CIBIL files contain income as a string with potential formatting (commas, empty strings, non-numeric entries). Parsing to numeric happens at the service layer via `_parse_income()`, which handles all these edge cases gracefully.

**Design decision — rpt_dt as String**: Similarly, `rpt_dt` is stored as a string to faithfully preserve the upstream format. Date parsing and comparison happen in the service layer. String comparison on YYYY-MM-DD formatted dates works correctly for range filtering in SQL.

### `identity_data`

**File**: `app/models/identity_data_model.py`

Stores identity document details keyed by `CUSTOMER_ID` per snapshot. This is a **sparse table** — not every customer has an identity record.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | Integer (PK) | No | Auto-increment primary key |
| `customer_id` | String(50) | Yes | Customer identifier (join key to main_data) |
| `pan` | String(20) | Yes | Permanent Account Number |
| `passport` | String(20) | Yes | Passport number |
| `voter_id` | String(30) | Yes | Voter ID number |
| `uid` | String(20) | Yes | UID / Aadhaar number |
| `ration_card` | Text | Yes | Ration card identifier |
| `driving_license` | String(30) | Yes | Driving license number |
| `snapshot_id` | Integer | Yes | Upload snapshot identifier |
| `created_at` | DateTime(tz) | No | Row creation timestamp (server default) |

**Indexes**:
- `ix_identity_data_customer_snapshot` — Composite on `(customer_id, snapshot_id)` for join performance
- Individual indexes on `customer_id`, `pan`, `snapshot_id`

**Join pattern**: Identity data is always joined to main data using:
```sql
LEFT JOIN identity_data ON (
    main_data.customer_id = identity_data.customer_id
    AND main_data.snapshot_id = identity_data.snapshot_id
)
```

This LEFT JOIN ensures customers without identity records still appear in results.

---

## Users & Auth Tables

### `users`

**File**: `app/models/user_model.py`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | Integer (PK) | No | Auto-increment primary key |
| `username` | String(50) | No | Unique username |
| `email` | String(255) | No | Unique email address |
| `hashed_password` | Text | No | bcrypt-hashed password |
| `role` | Enum(UserRole) | No | `admin` or `user` |
| `created_at` | DateTime(tz) | No | Registration timestamp (server default) |

**Indexes**: Unique indexes on `username` and `email`.

**Roles**: Defined via `UserRole` enum:
- `ADMIN` — Can upload files, manage users, view all audit logs
- `USER` — Can search customers, view details, export data

### `login_activity`

**File**: `app/models/login_activity_model.py`

Records every login attempt (both successful and failed) for audit compliance.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | Integer (PK) | No | Auto-increment primary key |
| `user_id` | Integer (FK → users) | Yes | NULL when user not found |
| `identifier` | String(255) | No | Login identifier used (email) |
| `email` | String(255) | Yes | Resolved email |
| `login_time` | DateTime(tz) | No | Timestamp of attempt |
| `ip_address` | String(64) | Yes | Client IP address |
| `user_agent` | String(512) | Yes | Client user agent string |
| `success` | Boolean | No | Whether login succeeded |
| `failure_reason` | String(64) | Yes | `user_not_found` or `invalid_credentials` |

**Indexes**:
- `ix_login_activity_login_time` — For time-ordered queries
- `ix_login_activity_email_login_time` — Composite for email + time queries

### `password_reset_tokens`

**File**: `app/models/password_reset_model.py`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | Integer (PK) | No | Auto-increment |
| `user_id` | Integer (FK → users) | No | Owner of the reset token |
| `token_hash` | String(128) | No | SHA-256 hash of the raw token |
| `expires_at` | DateTime(tz) | No | Token expiration (15 minutes from creation) |
| `used` | Boolean | No | Whether the token has been consumed |
| `created_at` | DateTime(tz) | No | Token creation timestamp |

**Security note**: Only the SHA-256 hash of the token is stored, never the raw token. The raw token is sent to the user (via email or DEBUG console) and hashed again during validation.

---

## Audit & Feature Tables

### `upload_history`

**File**: `app/models/upload_history_model.py`

Audit log of each bulk upload. Also serves as the source of `snapshot_id` values — `upload_history.id` IS the snapshot.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | Integer (PK) | No | Auto-increment; doubles as snapshot_id |
| `main_filename` | String(255) | No | Original filename of main data file |
| `identity_filename` | String(255) | No | Original filename of identity data file |
| `records_inserted` | Integer | No | Successfully inserted row count |
| `records_failed` | Integer | No | Failed row count |
| `uploaded_by` | Integer | Yes | User ID of uploader |
| `uploaded_at` | DateTime(tz) | No | Upload timestamp (server default) |
| `status` | String(20) | No | `success`, `partial`, or `failed` |

### `upload_errors`

**File**: `app/models/upload_error_model.py`

Per-row errors encountered during upload processing.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | Integer (PK) | No | Auto-increment |
| `upload_id` | Integer (FK → upload_history, CASCADE) | No | Which upload this error belongs to |
| `row_number` | Integer | No | Row number in the source file |
| `error_message` | Text | No | Description of the error |
| `raw_data` | Text | Yes | Truncated raw row data (max 1000 chars) |
| `created_at` | DateTime(tz) | No | Error record timestamp |

**Indexes**:
- `ix_upload_errors_upload_id` — For querying errors by upload
- `ix_upload_errors_created_at` — For time-ordered browsing

### `customer_view_activity`

**File**: `app/models/customer_view_activity_model.py`

Audit trail of which users viewed which customers.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | Integer (PK) | No | Auto-increment |
| `user_id` | Integer (FK → users) | No | Who viewed |
| `customer_id` | String(50) | No | Which customer was viewed |
| `viewed_at` | DateTime(tz) | No | When |

**Indexes**:
- `ix_customer_view_activity_user_id`
- `ix_customer_view_activity_customer_id`
- `ix_customer_view_activity_viewed_at`
- `ix_customer_view_activity_user_viewed_at` — Composite for user + time queries

### `saved_filters`

**File**: `app/models/saved_filter_model.py`

Persists user-created search filter presets as JSON.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | Integer (PK) | No | Auto-increment |
| `user_id` | Integer (FK → users) | No | Owner of the filter |
| `name` | String(255) | No | User-given name for the filter preset |
| `filters` | JSON | No | The filter parameters as a JSON object |
| `created_at` | DateTime(tz) | No | Creation timestamp |

**Indexes**:
- `ix_saved_filters_user_id`
- `ix_saved_filters_created_at`

---

## Entity Relationships

```
users ──────────────┬──── login_activity (1:N)
                    ├──── password_reset_tokens (1:N)
                    ├──── customer_view_activity (1:N)
                    ├──── saved_filters (1:N)
                    └──── upload_history.uploaded_by (1:N, no FK constraint)

upload_history ─────┬──── upload_errors (1:N, CASCADE delete)
                    └──── main_data.snapshot_id (1:N, logical FK)
                          identity_data.snapshot_id (1:N, logical FK)

main_data ──────────┬──── identity_data (joined via customer_id + snapshot_id)
```

**Note**: The relationship between `upload_history.id` and `main_data.snapshot_id` / `identity_data.snapshot_id` is a logical foreign key — there is no declared `ForeignKey` constraint at the ORM level. This is by design: it avoids cascade/lock overhead during high-throughput bulk inserts.

---

## Migration History

The `alembic/versions/` directory contains these migrations (listed chronologically by content, not filename):

| Migration | Purpose |
|-----------|---------|
| `f80f8975aa92` | Add `login_activity` and `password_reset_tokens` tables |
| `8fa600f657f2` | Add `customer_view_activity` audit logging table |
| `65c82670370c` | Add `user_viewed_at` composite index to `customer_view_activity` |
| `c2a3f9b1d7e4` | Add `upload_errors` table for row-level error logging |
| `7163b7701c4b` | Add composite index on `(snapshot_id, bank_type)` to `main_data` |
| `d0bb8cb3f7b5` | Add search/filter indexes to improve query performance |
| `0bcf7ab68f09` | Add `saved_filters` table |
| `9a1c2b3d4e5f` | Add `failure_reason` column and indexes to `login_activity` |
| `b3c4d5e6f7a8` | Add `identifier` column and make `email` nullable in `login_activity` |
| `df4b1b2c0a11` | Merge migration heads (upload_errors + customer_view index) |
