# API Documentation

## Base URL

```
http://localhost:8000
```

## Authentication

All endpoints except registration and password reset require a **JWT Bearer token** in the `Authorization` header:

```
Authorization: Bearer <jwt_token>
```

Tokens are issued via `POST /auth/login` and expire after 30 minutes. A **sliding-window refresh** mechanism automatically issues a new token with each authenticated request via the `X-New-Token` response header.

---

## Health Check

### `GET /`

Returns system health status. No authentication required.

**Response** `200`:
```json
{"status": "ok", "message": "System is healthy"}
```

---

## Authentication Endpoints

### `POST /auth/register`

Register a new user. Default role is `user`. Only an authenticated admin can create users with `role=admin`.

**Request Body**:
```json
{
    "username": "johndoe",
    "email": "john@example.com",
    "password": "secret123",
    "role": "user"
}
```

**Auth**: Optional (needed only to create admin users)

**Response** `201`:
```json
{
    "id": 1,
    "username": "johndoe",
    "email": "john@example.com",
    "role": "user",
    "created_at": "2025-03-16T12:00:00Z"
}
```

**Errors**:
- `400` — Username or email already exists
- `403` — Non-admin trying to create admin role

---

### `POST /auth/login`

Authenticate with email and password. Returns a JWT token.

**Request Body**:
```json
{
    "email": "john@example.com",
    "password": "secret123"
}
```

**Auth**: None

**Response** `200`:
```json
{
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer"
}
```

**Side effects**: Logs the login attempt (success or failure) to `login_activity` with IP address, user agent, and failure reason.

**Errors**:
- `401` — Invalid email or password

---

### `POST /auth/forgot-password`

Initiate password reset flow. Response is identical regardless of whether the email exists (prevents email enumeration).

**Request Body**:
```json
{"email": "user@example.com"}
```

**Auth**: None

**Response** `200`:
```json
{"message": "If the account exists, a password reset link will be sent."}
```

---

### `POST /auth/reset-password`

Complete password reset using the token received via email (or DEBUG console output).

**Request Body**:
```json
{
    "token": "reset-token-value",
    "new_password": "newSecret123"
}
```

**Auth**: None

**Response** `200`:
```json
{"message": "Password has been reset successfully."}
```

**Errors**:
- `400` — Invalid/used/expired token

---

### `GET /auth/me`

Get the currently authenticated user's details.

**Auth**: Required (any role)

**Response** `200`:
```json
{
    "id": 1,
    "username": "johndoe",
    "email": "john@example.com",
    "role": "user",
    "created_at": "2025-03-16T12:00:00Z"
}
```

---

## Admin Endpoints

All endpoints under `/admin` require `admin` role.

### `GET /admin/dashboard`

Aggregated analytics for the latest snapshot.

**Response** `200`:
```json
{
    "summary": {
        "total_customers": 125340,
        "total_records": 1002345,
        "latest_upload_date": "2025-03-16T12:00:00Z",
        "average_income": 75000.50
    },
    "bank_distribution": [
        {"bank_type": "PSU", "count": 50234},
        {"bank_type": "PVT", "count": 30120}
    ],
    "recent_uploads": [
        {
            "upload_id": 42,
            "records_inserted": 540234,
            "uploaded_at": "2025-03-16T12:00:00Z"
        }
    ]
}
```

---

### `GET /admin/login-activity`

Recent login attempts for auditing.

**Query Parameters**:
| Param | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `limit` | int | 50 | 1–200 | Max records to return |
| `offset` | int | 0 | ≥0 | Skip first N records |

**Response** `200`: Array of:
```json
{
    "id": 1,
    "user_id": 3,
    "identifier": "john@example.com",
    "email": "john@example.com",
    "login_time": "2025-03-16T12:00:00Z",
    "ip_address": "192.168.1.1",
    "user_agent": "Mozilla/5.0...",
    "success": true,
    "failure_reason": null
}
```

---

### `GET /admin/customer-view-activity`

Customer view audit logs.

**Query Parameters**: Same as login-activity (`limit`, `offset`)

**Response** `200`: Array of:
```json
{
    "id": 1,
    "user_id": 3,
    "customer_id": "CUST123",
    "viewed_at": "2025-03-16T12:00:00Z"
}
```

---

### `GET /admin/upload-errors`

Row-level errors for a specific upload.

**Query Parameters**:
| Param | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `upload_id` | int | **required** | ≥1 | Which upload to get errors for |
| `limit` | int | 50 | 1–500 | Max records |
| `offset` | int | 0 | ≥0 | Skip first N |

**Response** `200`: Array of:
```json
{
    "id": 1,
    "upload_id": 5,
    "row_number": 42,
    "error_message": "Missing CUSTOMER_ID",
    "raw_data": "{\"ACCT_KEY\": \"123\", ...}",
    "created_at": "2025-03-16T12:00:00Z"
}
```

---

### `GET /admin/users`

List all users.

**Response** `200`: Array of `UserResponse`.

### `POST /admin/users`

Create a new user (with role enforcement).

**Request Body**: Same as registration.

**Response** `201`: `UserResponse`

### `PATCH /admin/users/{user_id}`

Partial update of user details.

**Request Body** (all fields optional):
```json
{
    "username": "newname",
    "email": "new@example.com",
    "password": "newpassword",
    "role": "admin"
}
```

**Errors**:
- `403` — Cannot demote self, only admin can assign admin role
- `404` — User not found

### `DELETE /admin/users/{user_id}`

Delete a user.

**Errors**:
- `403` — Cannot delete self
- `404` — User not found

---

## User Endpoints

### `GET /user/dashboard`

Same dashboard analytics as admin, accessible by both admin and user roles.

**Auth**: `admin` or `user`

**Response**: Same as `GET /admin/dashboard`

---

## Customer Endpoints

### `GET /customers/search`

Search customers across the latest snapshot with optional filters.

**Auth**: Any authenticated user

**Query Parameters**:
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `customer_id` | string | None | Exact customer ID match |
| `pan` | string | None | Exact PAN match (from identity data) |
| `acct_key` | string | None | Exact account key match |
| `bank_type` | string | None | Exact bank type match |
| `occup_status_cd` | string | None | Exact occupation code match |
| `income_min` | int | None | Minimum income (inclusive) |
| `income_max` | int | None | Maximum income (inclusive) |
| `rpt_dt_from` | string | None | Start of date range (YYYY-MM-DD) |
| `rpt_dt_to` | string | None | End of date range (YYYY-MM-DD) |
| `last_customer_id` | string | None | Keyset pagination cursor |
| `page` | int | 1 | Page number (offset pagination) |
| `page_size` | int | 50 | Rows per page (max 500) |

**Pagination**: When `last_customer_id` is provided, keyset pagination is used (faster for large datasets). Otherwise falls back to traditional OFFSET pagination.

**Response** `200`:
```json
{
    "data": [
        {
            "customer_id": "CUST123",
            "acct_key": "ACCT001",
            "bank_type": "PSU",
            "income": "75000",
            "rpt_dt": "2025-01-31",
            "pan": "ABCDE****F"
        }
    ],
    "next_cursor": "CUST123"
}
```

**Note**: PAN values are masked in the response.

---

### `GET /customers/{customer_id}`

Get all joined main + identity records for a customer across all snapshots.

**Auth**: Any authenticated user

**Response** `200`: Array of:
```json
{
    "main_data": {
        "id": 1,
        "acct_key": "ACCT001",
        "customer_id": "CUST123",
        "income": "75000",
        "income_freq": "1",
        "occup_status_cd": "SAL",
        "rpt_dt": "2025-01-31",
        "bank_type": "PSU",
        "snapshot_id": 5,
        "created_at": "2025-03-16T12:00:00Z"
    },
    "identity_data": {
        "id": 1,
        "customer_id": "CUST123",
        "pan": "ABCDE****F",
        "passport": "A1****67",
        "voter_id": "AB*****67",
        "uid": "********9012",
        "ration_card": "RC********01",
        "driving_license": "DL********0001",
        "snapshot_id": 5,
        "created_at": "2025-03-16T12:00:00Z"
    }
}
```

**Side effects**: Logs a `customer_view_activity` record.

**Errors**: `404` — No records found

---

### `GET /customers/{customer_id}/timeline`

Full historical timeline across all snapshots, ordered by report date.

**Auth**: `admin` or `user`

**Response** `200`:
```json
{
    "customer_id": "CUST123",
    "timeline": [
        {
            "snapshot_id": 1,
            "uploaded_at": "2025-01-01T12:00:00Z",
            "rpt_dt": "2024-06-30",
            "income": "50000",
            "bank_type": "PSU",
            "occup_status_cd": "SAL",
            "pan": "ABCDE****F",
            "passport": null,
            "voter_id": null,
            "uid": "********9012",
            "driving_license": null,
            "ration_card": null
        }
    ]
}
```

**Side effects**: Logs a `customer_view_activity` record.

---

### `GET /customers/{customer_id}/income-trend`

Chart-ready income time series across all snapshots.

**Auth**: `admin` or `user`

**Response** `200`:
```json
[
    {"x": "2024-06-30", "y": 50000},
    {"x": "2025-01-31", "y": 75000}
]
```

---

### `GET /customers/{customer_id}/bank-trend`

Chart-ready bank type changes over time (only emits when bank type changes).

**Auth**: `admin` or `user`

**Response** `200`:
```json
[
    {"x": "2024-06-30", "y": "PSU"},
    {"x": "2025-01-31", "y": "PVT"}
]
```

---

### `GET /customers/{customer_id}/summary`

Analytical summary with five insight sections.

**Auth**: `admin` or `user`

**Response** `200`:
```json
{
    "profile": {
        "total_accounts": 5,
        "latest_income": 75000,
        "latest_bank_type": "PSU",
        "first_report_date": "2024-01-15",
        "latest_report_date": "2025-01-31"
    },
    "income_analysis": {
        "avg_income": 62500.0,
        "max_income": 75000,
        "min_income": 50000,
        "trend": "increasing",
        "volatility": "medium"
    },
    "bank_analysis": {
        "unique_bank_types": ["PSU", "PVT"],
        "bank_type_change_count": 1,
        "most_frequent_bank_type": "PSU"
    },
    "identity_analysis": {
        "identity_types_present": ["pan", "uid"],
        "identity_count": 2,
        "has_strong_identity": true,
        "latest_identity": {
            "pan": "ABCDE****F",
            "uid": "********9012"
        }
    },
    "timeline_insights": {
        "total_snapshots": 5,
        "reporting_span_days": 381,
        "activity_status": "active"
    }
}
```

---

### `GET /customers/export/csv`

Stream a CSV export of customer data using the same filters as search.

**Auth**: Any authenticated user

**Query Parameters**: Same filter parameters as `/customers/search` (without pagination params).

**Response**: `200` with `Content-Type: text/csv` streaming download.

CSV columns: `customer_id, acct_key, bank_type, income, income_freq, occup_status_cd, rpt_dt, snapshot_id, pan, passport, voter_id, uid, ration_card, driving_license`

All identity fields are masked in the export.

---

### `GET /customers/{customer_id}/report/pdf`

Download a structured PDF report for a customer.

**Auth**: `admin` or `user`

**Response**: `200` with `Content-Type: application/pdf` attachment download.

The PDF contains: Customer Overview, Account Information table, Identity Information, and Timeline table (if data exists).

**Errors**: `404` — No accounts found

---

## Upload Endpoints

### `POST /upload/files`

Upload main and identity CIBIL data files.

**Auth**: `admin` only

**Request**: `multipart/form-data` with:
- `main_file` — Main CIBIL data (.txt, pipe-separated)
- `identity_file` — Identity CIBIL data (.txt, pipe-separated)

**Response** `200`:
```json
{
    "message": "Upload completed",
    "records_inserted": 540234,
    "records_failed": 120,
    "status": "partial"
}
```

**Errors**: `400` — Files must be `.txt`

---

## Saved Filter Endpoints

### `POST /filters`

Save a customer search filter preset.

**Auth**: Any authenticated user

**Request Body**:
```json
{
    "name": "High income PSU customers",
    "filters": {
        "bank_type": "PSU",
        "income_min": 100000
    }
}
```

**Response** `201`:
```json
{
    "id": 1,
    "name": "High income PSU customers",
    "filters": {"bank_type": "PSU", "income_min": 100000},
    "created_at": "2025-03-16T12:00:00Z"
}
```

### `GET /filters`

List current user's saved filter presets.

**Response** `200`: Array of `SavedFilterResponse`.

### `DELETE /filters/{filter_id}`

Delete a saved filter. Only the owner can delete their filters.

**Response** `200`:
```json
{"message": "Saved filter deleted"}
```

---

## Upload History

### `GET /uploads/history`

List all upload history records, ordered by most recent first.

**Auth**: Any authenticated user

**Response** `200`: Array of:
```json
{
    "id": 5,
    "main_filename": "main_data.txt",
    "identity_filename": "identity_data.txt",
    "records_inserted": 540234,
    "records_failed": 120,
    "uploaded_by": 1,
    "uploaded_at": "2025-03-16T12:00:00Z",
    "status": "partial"
}
```

---

## Common Error Responses

| Status | Meaning |
|--------|---------|
| `400` | Bad request (validation error, invalid ranges) |
| `401` | Not authenticated or invalid/expired token |
| `403` | Insufficient permissions for the role |
| `404` | Resource not found |
| `422` | Pydantic validation error |

## Token Refresh Mechanism

Every authenticated request triggers a **sliding-window token refresh**. The server issues a new JWT (with a fresh 30-minute expiration and updated `last_activity` timestamp) and returns it in the `X-New-Token` response header. The client should read this header and replace its stored token. If the client has been inactive for more than 30 minutes (1800 seconds), the request is rejected with a `401 Session expired due to inactivity` error.
