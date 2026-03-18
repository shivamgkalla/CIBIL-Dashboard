# Architecture Overview

## What This System Is

The CIBIL Dashboard is a **FastAPI-based backend** that ingests, stores, queries, and reports on CIBIL (Credit Information Bureau India Limited) credit bureau data. It serves as an internal tool for viewing customer credit snapshots, tracking changes over time, generating PDF reports, and exporting data — all behind JWT-based authentication with role-based access control (RBAC).

## Why It Exists

Credit bureaus deliver data in pipe-separated flat files. This system transforms those raw files into a queryable, searchable, audit-logged platform that:

- Allows admin users to upload new snapshots of bureau data
- Lets both admin and regular users search, view, and analyze customer records
- Provides timeline views showing how a customer's data has changed across uploads
- Generates analytical summaries and downloadable PDF reports
- Masks sensitive identity data (PAN, Aadhaar, passport) in all API responses
- Logs every login attempt and customer view for audit compliance

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Framework | FastAPI 0.135.1 | Async-ready REST API framework |
| ORM | SQLAlchemy 2.0.48 | Database abstraction with mapped columns |
| Database | PostgreSQL (psycopg2-binary) | Primary data store |
| Migrations | Alembic 1.18.4 | Schema versioning and migrations |
| Auth | python-jose + passlib (bcrypt) | JWT tokens and password hashing |
| Validation | Pydantic 2.12.5 + pydantic-settings | Request/response validation and config |
| PDF | ReportLab 4.2.5 | PDF report generation |
| Server | Uvicorn 0.41.0 | ASGI server |

## Directory Structure

```
cibil_dashboard/
├── app/
│   ├── main.py                          # FastAPI app entry point
│   ├── core/
│   │   ├── config.py                    # Pydantic Settings (env vars)
│   │   └── security.py                  # JWT + bcrypt utilities
│   ├── db/
│   │   ├── base.py                      # SQLAlchemy DeclarativeBase
│   │   └── database.py                  # Engine, SessionLocal, get_db
│   ├── dependencies/
│   │   └── role_checker.py              # RBAC, JWT validation, sliding-window refresh
│   ├── models/                          # 9 ORM models
│   │   ├── main_data_model.py           # Core CIBIL account data
│   │   ├── identity_data_model.py       # Identity documents (PAN, UID, etc.)
│   │   ├── user_model.py               # Users with admin/user roles
│   │   ├── upload_history_model.py      # Upload run audit log
│   │   ├── upload_error_model.py        # Per-row upload errors
│   │   ├── login_activity_model.py      # Login attempt audit
│   │   ├── password_reset_model.py      # Password reset tokens
│   │   ├── customer_view_activity_model.py  # Customer view audit
│   │   └── saved_filter_model.py        # User-saved search filters
│   ├── routers/                         # 6 route modules
│   │   ├── auth_router.py               # /auth/* (register, login, reset)
│   │   ├── admin_router.py              # /admin/* (dashboard, users, audit)
│   │   ├── user_router.py               # /user/* (user dashboard)
│   │   ├── upload_router.py             # /upload/* (file upload)
│   │   ├── customer_router.py           # Customer search, detail, timeline, export
│   │   └── saved_filter_router.py       # /filters/* (saved filter CRUD)
│   ├── schemas/                         # 12 Pydantic schema modules
│   │   ├── user_schema.py
│   │   ├── customer_schema.py
│   │   ├── customer_summary_schema.py
│   │   ├── customer_timeline_schema.py
│   │   ├── customer_view_activity_schema.py
│   │   ├── chart_schema.py
│   │   ├── dashboard_schema.py
│   │   ├── login_activity_schema.py
│   │   ├── password_reset_schema.py
│   │   ├── saved_filter_schema.py
│   │   ├── upload_schema.py
│   │   └── upload_error_schema.py
│   ├── services/                        # 10 service modules
│   │   ├── auth_service.py
│   │   ├── user_service.py
│   │   ├── upload_service.py
│   │   ├── customer_service.py          # ~1000 lines, the heaviest module
│   │   ├── customer_view_activity_service.py
│   │   ├── dashboard_service.py
│   │   ├── login_activity_service.py
│   │   ├── password_reset_service.py
│   │   ├── pdf_service.py
│   │   └── saved_filter_service.py
│   └── utils/
│       └── masking.py                   # Identity field masking utilities
├── alembic/                             # Migration versions
├── alembic.ini
├── requirements.txt
├── .env.example
└── generate_cibil_test_data.py          # Test data generator script
```

## Layered Architecture

The system follows a strict **three-layer architecture**:

```
┌──────────────────────────────────────────────┐
│                  Routers                      │
│  (HTTP concerns: validation, status codes,    │
│   dependency injection, response formatting)  │
├──────────────────────────────────────────────┤
│                  Services                     │
│  (Business logic: queries, analytics,         │
│   masking, data transformation)               │
├──────────────────────────────────────────────┤
│              Models / Database                │
│  (ORM models, sessions, migrations)           │
└──────────────────────────────────────────────┘
```

**Key design rule**: Routers never contain business logic. They validate inputs, call the appropriate service function, and format the HTTP response. Masking of sensitive data happens exclusively in the service layer, never in routers and never on stored data.

## Application Lifecycle

The FastAPI app is defined in `app/main.py` with a lifespan context manager (currently a no-op `yield` that reserves the hook for future startup/shutdown logic):

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="CIBIL Bureau", version="1.0.0", lifespan=lifespan)
```

Six routers are mounted onto the app:

| Router | Prefix | Auth |
|--------|--------|------|
| `auth_router` | `/auth` | Mixed (some public, some authenticated) |
| `admin_router` | `/admin` | Admin only |
| `user_router` | `/user` | Admin or user |
| `upload_router` | `/upload` | Admin only |
| `customer_router` | (none) | Authenticated (varies by endpoint) |
| `saved_filter_router` | (none) | Authenticated |

A health check endpoint exists at `GET /` returning `{"status": "ok", "message": "System is healthy"}`.

## Configuration

All configuration is loaded from environment variables (with `.env` file support) via Pydantic Settings in `app/core/config.py`. The `Settings` class is cached with `@lru_cache` so it is instantiated exactly once.

Required variables:
- `DATABASE_URL` — PostgreSQL connection string
- `SECRET_KEY` — JWT signing secret

Optional variables with defaults:
- `ACCESS_TOKEN_EXPIRE_MINUTES` (default: 30)
- `ALGORITHM` (default: HS256)
- `DEBUG` (default: False)
- `SMTP_*` — for password reset email delivery
- `RESET_LINK_BASE_URL` — base URL for password reset links

If a required variable is missing at startup, the system raises a `RuntimeError` with a clear message listing the missing variable names.

## Database Strategy

- **Engine**: PostgreSQL with `pool_pre_ping=True` for connection health checking
- **Sessions**: `sessionmaker` with `autocommit=False, autoflush=False` — explicit transaction control
- **Schema management**: Alembic migrations only. `Base.metadata.create_all()` is deliberately never called. All schema changes go through versioned migration scripts
- **Dependency injection**: The `get_db()` generator yields a session per request and ensures cleanup via `finally: db.close()`

## Key Design Decisions

1. **Snapshot-based data model**: Each upload creates a "snapshot" (identified by `UploadHistory.id`). Customer data is always queried relative to a snapshot, enabling full historical tracking without overwriting previous data.

2. **Identity data is separate**: Main data and identity data live in separate tables, joined by `(customer_id, snapshot_id)`. This reflects the upstream file structure and allows identity data to be sparse (not all customers have identity records).

3. **Masking at response layer only**: Sensitive fields (PAN, UID, passport, etc.) are masked only when constructing API responses. Database storage remains unmasked, preserving data integrity for internal use.

4. **No CORS middleware configured**: The app currently does not include CORS configuration, suggesting it may sit behind a reverse proxy or be consumed by a same-origin frontend.

5. **Synchronous ORM, async-ready framework**: While FastAPI supports async, the database operations use synchronous SQLAlchemy sessions. This is a pragmatic choice — the app is CPU-bound during analytics computation, and psycopg2 is synchronous.
