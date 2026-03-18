# Future Improvements

## Overview

This document catalogs concrete, actionable improvements based on gaps observed in the current codebase. Each item includes the problem, the suggested solution, and affected files.

---

## High Priority

### 1. Add Application-Level Caching

**Problem**: Every request hits the database directly. The dashboard endpoint runs multiple aggregate queries on each call. Customer summary analytics recomputes from scratch on every request.

**Suggestion**:
- Add Redis (or in-memory TTL cache) for:
  - Dashboard data (cache for 30–60 seconds)
  - Customer summary analytics (cache per customer_id for 5 minutes)
  - Latest snapshot ID (cache for 10 seconds — changes only on upload)
- Invalidate relevant caches when a new upload completes

**Affected files**: `app/services/dashboard_service.py`, `app/services/customer_service.py`, `app/core/config.py` (add Redis URL)

### 2. Add CORS Configuration

**Problem**: No CORS middleware is configured. If the frontend runs on a different origin (common in dev and production), API requests will be blocked by browsers.

**Suggestion**:
```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,  # from config
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-New-Token"],  # needed for sliding window refresh
)
```

**Affected files**: `app/main.py`, `app/core/config.py`

### 3. Add Request ID / Correlation Tracking

**Problem**: No way to trace a single API request through database queries and service calls. When debugging production issues, there is no correlation between log entries.

**Suggestion**:
- Add middleware that generates a UUID for each request
- Pass the request ID through the `logging` context (using `logging.Filter` or `contextvars`)
- Include request ID in all structured log `extra` fields
- Return request ID in a response header (`X-Request-ID`)

**Affected files**: `app/main.py` (middleware), all service modules (logging context)

### 4. Async Database Operations

**Problem**: SQLAlchemy sessions are synchronous. Each database query blocks a uvicorn worker thread. Under high concurrent load, this limits throughput.

**Suggestion**:
- Migrate to `asyncpg` + SQLAlchemy async engine
- Convert `get_db()` to an async generator
- Use `async with AsyncSession()` in services
- This is a significant refactor — estimate 2–3 days

**Affected files**: All services, all routers, `app/db/database.py`

---

## Medium Priority

### 5. Connection Pool Tuning

**Problem**: Default SQLAlchemy pool settings are used. No explicit `pool_size`, `max_overflow`, or `pool_timeout`. Under load, this could lead to connection exhaustion or excessive connections.

**Suggestion**:
```python
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=3600,
)
```

**Affected files**: `app/db/database.py`, `app/core/config.py` (add pool settings)

### 6. Health Check Depth

**Problem**: The health endpoint (`GET /`) returns a static response without verifying database connectivity. A healthy HTTP response with a dead database connection misleads monitoring.

**Suggestion**:
```python
@app.get("/", tags=["Health"])
def root(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "disconnected"},
        )
```

**Affected files**: `app/main.py`

### 7. Email Integration for Password Reset

**Problem**: Password reset links are only printed to the terminal in DEBUG mode. In production, the email sending is a placeholder `pass` statement.

**Suggestion**:
- Implement SMTP email sending using the already-configured `SMTP_*` settings
- Use `smtplib` or `aiosmtplib` to send the reset link
- Add HTML email template
- The config already supports `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`

**Affected files**: `app/services/password_reset_service.py`

### 8. JSON Log Formatter

**Problem**: Structured logging uses `extra` fields, but the default Python formatter doesn't render them. Valuable context (customer_id, counts) is lost in production logs.

**Suggestion**:
- Add `python-json-logger` or configure a custom JSON formatter
- Set up in `app/main.py` lifespan or a dedicated `app/core/logging.py`
- All existing `extra={}` calls would immediately benefit

**Affected files**: `app/main.py` or new `app/core/logging.py`

### 9. Audit Logging for Admin Actions

**Problem**: User CRUD operations (create, update, delete) are not logged anywhere. Only login attempts and customer views are tracked. An admin could delete a user with no audit trail.

**Suggestion**:
- Create an `admin_action_log` table (or repurpose a generic audit table)
- Log: action type, admin user_id, target user_id, timestamp, changes
- Add logging in `user_service.py` functions

**Affected files**: New model, new migration, `app/services/user_service.py`

### 10. Log Audit Logging Failures

**Problem**: When `log_customer_view()` fails in the router, the exception is silently swallowed:
```python
except Exception:
    db.rollback()
```

This means audit logging failures are invisible to operators.

**Suggestion**:
```python
except Exception:
    db.rollback()
    log.warning("Failed to log customer view", extra={"customer_id": customer_id}, exc_info=True)
```

**Affected files**: `app/routers/customer_router.py`

---

## Low Priority

### 11. Pagination for Upload History

**Problem**: `get_upload_history()` returns ALL upload history records without pagination. If the system runs for years with frequent uploads, this list will grow unbounded.

**Suggestion**:
- Add `limit` and `offset` parameters to the function and endpoint
- Consistent with how login activity and customer view activity already work

**Affected files**: `app/services/customer_service.py`, `app/routers/customer_router.py`

### 12. PDF Enhancements

**Problem**: PDFs lack page numbers, watermarks, branding, and charts. Fixed column widths may not be optimal.

**Suggestion**:
- Add page numbering via a custom `PageTemplate` or `onPage` callback
- Add a "Confidential" watermark
- Add company logo to header
- Include income trend chart using ReportLab's drawing/charts module
- Dynamic column widths based on content

**Affected files**: `app/services/pdf_service.py`

### 13. Rate Limiting

**Problem**: No rate limiting exists. The login endpoint, password reset endpoint, and data-heavy endpoints (search, export) are vulnerable to abuse.

**Suggestion**:
- Add `slowapi` (FastAPI-compatible rate limiter) or custom middleware
- Recommended limits:
  - Login: 5 attempts per minute per IP
  - Password reset: 3 requests per hour per email
  - CSV export: 5 per minute per user
  - PDF report: 10 per minute per user

**Affected files**: `app/main.py`, relevant routers

### 14. Automated Testing

**Problem**: No test files exist in the project. All testing is manual.

**Suggestion**:
- Add `pytest` + `httpx` (for TestClient)
- Create test fixtures for database sessions (use SQLite in-memory or test PostgreSQL)
- Priority test targets:
  1. Masking functions (pure functions, easy to test)
  2. Income/date parsing (edge cases documented)
  3. Upload service (mock file objects)
  4. Customer service analytics (complex logic)
  5. Auth flow (registration, login, password reset)
  6. RBAC enforcement (role-based access)

**Affected files**: New `tests/` directory

### 15. API Versioning

**Problem**: All endpoints are unversioned. Breaking changes would affect all consumers simultaneously.

**Suggestion**:
- Add `/api/v1/` prefix to all routers
- Or use header-based versioning
- Plan for v2 when breaking changes are needed

**Affected files**: `app/main.py`, all routers

### 16. Upload Progress Tracking

**Problem**: Large file uploads (200K+ rows) take time, but the client gets no feedback until completion. The upload endpoint blocks until all processing is done.

**Suggestion**:
- Use background task processing (Celery or FastAPI `BackgroundTasks`)
- Return immediately with an `upload_id`
- Add `GET /upload/{upload_id}/status` endpoint for polling
- Update `UploadHistory` with progress percentage during processing

**Affected files**: `app/routers/upload_router.py`, `app/services/upload_service.py`

### 17. Data Retention / Cleanup

**Problem**: Old snapshots are never cleaned up. Over time, the database will grow unbounded as each upload adds a full set of data.

**Suggestion**:
- Add admin endpoint to delete old snapshots (cascading main_data + identity_data)
- Or add an automated retention policy (keep last N snapshots)
- Add row counts to the delete confirmation

**Affected files**: New service function, new router endpoint, new migration (if cascade needed)

### 18. Streaming Identity Map for Large Files

**Problem**: `_build_identity_map()` loads the entire identity file into memory. For very large identity files, this could exhaust available RAM.

**Suggestion**:
- For identity files > N rows, write to a temporary SQLite database or use pandas chunked reading
- Or pre-sort both files by CUSTOMER_ID and do a merge join

**Affected files**: `app/services/upload_service.py`

---

## Not Implemented Features to Call Out

These are things that might be expected but are explicitly NOT present in the current codebase:

1. **No full-text search** — Customer search is exact-match only (no LIKE, no trigram, no Elasticsearch)
2. **No data export formats beyond CSV** — No Excel (XLSX), no JSON export endpoint
3. **No webhooks or notifications** — No event-driven alerts on upload completion or data anomalies
4. **No multi-tenancy** — All users see the same data. No organization or team-level isolation
5. **No file format auto-detection** — Files must be pipe-separated TXT. No CSV, no tab-separated, no Excel upload support
6. **No data deduplication** — If the same file is uploaded twice, all records are inserted again as a new snapshot
7. **No snapshot comparison** — Cannot diff two snapshots to see what changed
8. **No user activity dashboard** — The current user has no way to see their own activity (viewed customers, etc.)
