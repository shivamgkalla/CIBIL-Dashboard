# Logging and Observability

## Overview

The system uses Python's standard `logging` module with structured logging patterns. Logging is intentional — only meaningful events are logged, and sensitive data is never included in log output.

---

## Logger Setup

Each service module creates its own logger:

```python
import logging
log = logging.getLogger(__name__)
```

In `customer_service.py`:
```python
log = logging.getLogger(__name__)
```

In `upload_service.py`:
```python
logger = logging.getLogger(__name__)
```

The loggers inherit the root logger's configuration. No custom handlers or formatters are configured at the application level — this is left to the deployment environment (uvicorn's default logging, or a custom logging configuration).

---

## Log Levels Used

### INFO Level

Used for significant business events that should be visible in production logs.

**Customer summary generation**:
```python
log.info("Generating summary", extra={"customer_id": customer_id})
```

This is the only `info` log in the customer service. It marks the beginning of a potentially expensive analytics computation.

### WARNING Level

Used for situations that are not errors but indicate potential issues.

**No data for customer** (in summary analytics):
```python
log.warning("No data for customer", extra={"customer_id": customer_id})
```

Logged when `get_customer_summary_analytics()` is called for a customer_id that has no data. This could indicate a frontend bug (calling summary for a non-existent customer) or a data gap.

**Large dataset detection**:
```python
if len(details) > 5000:
    log.warning(
        "Large dataset for customer",
        extra={"customer_id": customer_id, "details_count": len(details)},
    )
```

Logged when a customer has more than 5000 detail records. This is an early warning for potential performance issues — the analytics will still compute, but slowly.

### DEBUG Level

Used for diagnostic information that is only useful during development or troubleshooting.

**Income parse failures**:
```python
if income_parse_failures:
    log.debug(
        "Parsing failed",
        extra={"field": "income", "count": income_parse_failures, "customer_id": customer_id},
    )
```

**Report date parse failures**:
```python
if rpt_dt_parse_failures:
    log.debug(
        "Parsing failed",
        extra={"field": "rpt_dt", "count": rpt_dt_parse_failures, "customer_id": customer_id},
    )
```

These log the COUNT of parse failures, not the actual values. This helps identify data quality issues without flooding logs with individual failure details.

### ERROR Level (via `logger.exception`)

Used for unexpected errors during upload processing.

**Batch insert failure**:
```python
logger.exception(
    "Bulk insert failed for batch of %d main rows (and matching identity rows). "
    "Marked rows as failed and continuing ingestion.",
    failed_rows,
)
```

**Error recording failure**:
```python
logger.exception(
    "Failed to persist upload error rows for snapshot_id=%s", snapshot_id
)
```

`logger.exception()` automatically includes the full traceback, which is critical for debugging database-level insert failures.

---

## What Is Logged

| Event | Level | Module | Extra Data |
|-------|-------|--------|------------|
| Summary generation started | INFO | customer_service | `customer_id` |
| No data for customer summary | WARNING | customer_service | `customer_id` |
| Large dataset detected (>5000) | WARNING | customer_service | `customer_id`, `details_count` |
| Income parse failures | DEBUG | customer_service | `field`, `count`, `customer_id` |
| Report date parse failures | DEBUG | customer_service | `field`, `count`, `customer_id` |
| Batch insert failure | ERROR | upload_service | `failed_rows` (count), full traceback |
| Error row persistence failure | ERROR | upload_service | `snapshot_id`, full traceback |

---

## What Is NOT Logged

The following items are deliberately excluded from logs:

### Sensitive Data

- **Passwords** — Never logged in any form (raw or hashed)
- **JWT tokens** — Never logged
- **Password reset tokens** — Never logged (the `_build_reset_link()` docstring explicitly notes: "token never logged in production")
- **Raw identity data** — PAN, Aadhaar, passport, etc. are never in log output
- **Raw income values** — Only failure counts are logged, not actual values

### High-Volume Events

- **Individual row processing** — No per-row logging during upload (would be millions of log lines)
- **Individual search queries** — No logging of search parameters or results
- **Individual masking operations** — No logging of masking input/output
- **Successful batch inserts** — Only failures are logged during upload

### Routine Events

- **Request/response** — Handled by uvicorn/FastAPI's default access logs
- **Token refresh** — Sliding-window refresh happens silently
- **Audit log writes** — Customer view and login activity are persisted to the database, not to logs

---

## Structured Logging Pattern

The codebase uses the `extra` parameter for structured context:

```python
log.info("Generating summary", extra={"customer_id": customer_id})
log.warning("Large dataset for customer", extra={"customer_id": customer_id, "details_count": len(details)})
log.debug("Parsing failed", extra={"field": "income", "count": income_parse_failures, "customer_id": customer_id})
```

This pattern allows log aggregation tools (ELK, Datadog, etc.) to index and filter by `customer_id`, `field`, `count`, etc. However, the default Python formatter doesn't render `extra` fields — a JSON formatter would need to be configured in production to take advantage of this.

---

## SQL Logging

```python
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=settings.DEBUG,
)
```

When `DEBUG=True` in the environment, SQLAlchemy logs every SQL statement to stdout via `echo=True`. This is invaluable for query debugging but should never be enabled in production (performance and log volume).

---

## Database-Level Audit Trail

Instead of logging customer access to files, the system stores audit data in the database:

### Login Activity (`login_activity` table)

Captures every authentication attempt with:
- Who tried to log in (`identifier`, `email`)
- Whether it succeeded (`success`)
- Why it failed (`failure_reason`: `"user_not_found"` or `"invalid_credentials"`)
- Where they connected from (`ip_address`, `user_agent`)
- When (`login_time`)

Queryable via `GET /admin/login-activity` with pagination.

### Customer View Activity (`customer_view_activity` table)

Captures every customer detail/timeline view with:
- Who viewed (`user_id`)
- Which customer (`customer_id`)
- When (`viewed_at`)

Queryable via `GET /admin/customer-view-activity` with pagination.

### Upload History & Errors

- `upload_history` — Every upload with filename, counts, status, uploader
- `upload_errors` — Per-row errors with row number, error message, truncated raw data

Queryable via `GET /uploads/history` and `GET /admin/upload-errors?upload_id=N`.

---

## Debug Mode

When `DEBUG=True`:

1. **SQL echo** — All SQL statements logged to stdout
2. **Password reset links** — Printed to terminal (instead of sent via email)

```python
if settings.DEBUG:
    print("\n" + "=" * 60)
    print("[DEV] Password reset link (do not use in production):")
    print(link)
    print("=" * 60 + "\n")
```

---

## Observability Gaps

Honest assessment of what is NOT currently observable:

1. **No request tracing** — No request IDs, no correlation between API calls and database queries
2. **No metrics** — No Prometheus endpoints, no response time tracking, no error rate counters
3. **No health check depth** — The `GET /` health check only returns a static response; it doesn't verify database connectivity
4. **No alerting hooks** — Large dataset warnings and upload failures are logged but not integrated with any alerting system
5. **No JSON log formatter** — Structured `extra` data is captured but not rendered by the default formatter
6. **No audit log for admin actions** — User CRUD operations (create, update, delete) are not logged to any audit trail. Only login and customer view activities are tracked
7. **Silent audit failures** — When `log_customer_view()` fails, the exception is caught and the error is swallowed without logging:
   ```python
   except Exception:
       db.rollback()
   ```
   This means audit logging failures are invisible
