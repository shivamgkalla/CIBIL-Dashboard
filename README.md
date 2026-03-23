# CIBIL Bureau Dashboard — Backend

FastAPI backend for ingesting, querying, and reporting on CIBIL credit bureau data. Handles multi-file pipe-separated uploads with auto-detection, historical snapshots, customer search with identity filters, analytics, PDF/CSV export, and full audit logging — all behind JWT auth with RBAC.

**Live**: https://cibil-backend-yx2e.onrender.com

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | FastAPI 0.135.1 |
| Database | PostgreSQL (SQLAlchemy 2.0, Alembic migrations) |
| Auth | JWT (HS256) via python-jose + bcrypt via passlib |
| PDF Export | ReportLab 4.2.5 |
| Rate Limiting | SlowAPI (per-IP, in-memory) |
| Server | Uvicorn 0.41.0 |
| Deployment | Render (free tier) |
| Python | 3.12+ |

---

## Quick Start

```bash
# Clone and setup
git clone git@github.com:shivamgkalla/CIBIL-Dashboard.git
cd CIBIL-Dashboard
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env — set DATABASE_URL and SECRET_KEY at minimum

# Run migrations
alembic upgrade head

# Seed initial admin user (reads ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_PASSWORD from env)
python seed_admin.py

# Start server
uvicorn app.main:app --reload
```

Interactive API docs: [Swagger UI](http://localhost:8000/docs) | [ReDoc](http://localhost:8000/redoc)

---

## API Endpoints

### Health

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | None | Health check with DB connectivity verification |

### Authentication (`/auth`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/register` | Optional | Register a new user (admin can set role=admin) |
| POST | `/auth/login` | None | Login with email + password, returns JWT (rate-limited: 5/min) |
| POST | `/auth/forgot-password` | None | Initiate password reset (rate-limited: 3/min) |
| POST | `/auth/reset-password` | None | Complete password reset with token |
| GET | `/auth/me` | Any | Get current user profile |

### File Upload (`/upload`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/upload/files` | Admin | Upload N pipe-separated .txt files (async background processing) |
| GET | `/upload/status/{upload_id}` | Any | Poll upload progress (rows processed, inserted, failed) |

### Customer Search & Detail (`/customers`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/customers/search` | Any | Search with filters + keyset/offset pagination |
| GET | `/customers/{id}` | Any | Full joined main + identity records (all snapshots) |
| GET | `/customers/{id}/timeline` | Admin/User | Historical timeline across all snapshots |
| GET | `/customers/{id}/summary` | Admin/User | Analytics summary (income, bank, identity, timeline) |

**Search filters**: `customer_id`, `pan`, `phone`, `acct_key`, `bank_type`, `occup_status_cd`, `income_min`, `income_max`, `rpt_dt_from`, `rpt_dt_to`

### Charts

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/customers/{id}/income-trend` | Admin/User | Per-customer income time series |
| GET | `/customers/{id}/bank-trend` | Admin/User | Per-customer bank type changes |
| GET | `/charts/global/income-trend` | Admin/User | Global avg income by report date (filterable) |
| GET | `/charts/global/bank-distribution` | Admin/User | Global bank type distribution (filterable) |

### Export

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/customers/export/csv` | Any | Streaming CSV export (same filters as search) |
| GET | `/customers/{id}/report/pdf` | Admin/User | Bureau-style PDF report download |

### Dashboard & Admin (`/admin`, `/user`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/user/dashboard` | Admin/User | Dashboard analytics (cached 60s) |
| GET | `/admin/dashboard` | Admin | Admin dashboard analytics (cached 60s) |
| GET | `/admin/users` | Admin | List all users |
| POST | `/admin/users` | Admin | Create user |
| PATCH | `/admin/users/{user_id}` | Admin | Update user |
| DELETE | `/admin/users/{user_id}` | Admin | Delete user (self-delete protected) |
| GET | `/admin/login-activity` | Admin | Login attempt audit log (paginated) |
| GET | `/admin/customer-view-activity` | Admin | Customer view audit log (paginated) |
| GET | `/admin/upload-errors` | Admin | Row-level upload errors for a given upload |
| GET | `/admin/admin-activity` | Admin | Admin action audit trail (paginated) |

### Saved Filters (`/filters`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/filters` | Any | Save a search filter preset |
| GET | `/filters` | Any | List current user's saved filters |
| DELETE | `/filters/{filter_id}` | Any | Delete a saved filter (owner only) |

### Upload History

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/uploads/history` | Any | Paginated upload history (limit/offset) |

---

## Upload System

The upload endpoint accepts N pipe-separated `.txt` files and auto-classifies each by its header row:

| File Type | Detection Header | Target Table |
|-----------|-----------------|--------------|
| **Account** | `ACCT_KEY` | `main_data` (income, bank_type, rpt_dt, etc.) |
| **Credit Score** | `SCORE_V3` or `CUST_ID` (<=3 cols) | Enriches `main_data.credit_score` |
| **Identity Docs** | `PAN`, `PASSPORT`, or `VOTER_ID` | `identity_data` |
| **Phone** | `PHONE` (without `EMAIL`) | `identity_data.phone` |
| **Personal** | `FULL_NAME` or `DOB` + `GENDER` | `main_data` (full_name, dob, gender) |
| **Email** | `EMAIL` (without `PHONE`) | `identity_data.email` |
| **Address** | `ADDRESS` or `PINCODE` | `identity_data` (address, pincode) |
| **Inquiry** | `INQ_PURP_CD` | `inquiry_data` |

**Processing**: Uploads run asynchronously in background with real-time progress tracking. Poll `GET /upload/status/{id}` for status updates. Files can be uploaded standalone (without an account file) — each type inserts directly into its target table.

**Batch processing**: Records are inserted in batches of 10,000 with row-level error logging. Progress is updated every 5,000 rows.

---

## Database Schema

11 tables managed via Alembic migrations (16 migration files):

| Table | Purpose |
|-------|---------|
| `users` | User accounts with role (admin/user) and last_login |
| `main_data` | Core account-level CIBIL data per snapshot |
| `identity_data` | Identity documents + contact info per snapshot |
| `inquiry_data` | Credit inquiry records per snapshot |
| `upload_history` | Upload metadata, status, progress tracking |
| `upload_errors` | Row-level error logging for failed rows |
| `login_activity` | Login attempt tracking (success/failure with reason) |
| `password_reset_tokens` | SHA256-hashed time-limited reset tokens |
| `customer_view_activity` | Audit log for customer record views |
| `admin_activity` | Admin action audit trail (create/update/delete user) |
| `saved_filters` | User-saved search filter presets (JSON) |

### Snapshot Model

Every upload creates a **snapshot** (`upload_history.id`). All records from one upload share the same `snapshot_id`. Search endpoints query only the latest successful snapshot. Timeline/detail endpoints span all snapshots for historical data.

### Key Indexes

- `main_data`: composite `(customer_id, snapshot_id)`, `acct_key`, `occup_status_cd`, `rpt_dt`
- `identity_data`: composite `(customer_id, snapshot_id)`, `pan`, `phone`
- `inquiry_data`: composite `(customer_id, snapshot_id)`
- `login_activity`: `login_time`, composite `(email, login_time)`
- `customer_view_activity`: `user_id`, `customer_id`, `viewed_at`, composite `(user_id, viewed_at)`
- `admin_activity`: `performed_at`, `admin_id`, `action`
- `upload_errors`: `upload_id`, `created_at`
- `saved_filters`: `user_id`, `created_at`

---

## Security

### Authentication & Authorization
- JWT tokens (HS256) with configurable expiry (default 30 min)
- Sliding-window token refresh via `X-New-Token` response header
- 30-minute inactivity timeout (server-side check on `last_activity` claim)
- Role-based access control: `admin` and `user` roles
- bcrypt password hashing with 72-byte truncation for safety
- Password reset via SHA256-hashed tokens with 15-minute expiry

### Rate Limiting
- `/auth/login`: 5 requests/minute per IP
- `/auth/forgot-password`: 3 requests/minute per IP

### PII Masking

All identity fields are masked at the service layer before leaving the API — raw data is never exposed:

| Field | Mask Pattern | Example |
|-------|-------------|---------|
| PAN | First 5 + last 1 | `ABCDE****F` |
| UID/Aadhaar | Last 4 only | `********3333` |
| Passport | First 2 + last 2 | `J1****67` |
| Driving License | First 2 + last 4 | `DL**********2345` |
| Voter ID | First 2 + last 2 | `VO******67` |
| Ration Card | First 2 + last 2 | `RA******43` |
| Phone | Last 4 only | `******3210` |
| Email | First 2 of local + domain | `ra**********@example.com` |

Address and pincode are returned unmasked.

---

## Project Structure

```
app/
├── main.py                    # FastAPI app, CORS, lifespan (stuck upload cleanup)
├── core/
│   ├── config.py              # Pydantic Settings (env vars, dev/prod mode)
│   ├── security.py            # JWT creation/validation + bcrypt hashing
│   └── rate_limit.py          # SlowAPI limiter config
├── db/
│   ├── base.py                # SQLAlchemy DeclarativeBase
│   └── database.py            # Engine, session pool (10+20 overflow), get_db
├── dependencies/
│   └── role_checker.py        # RBAC guards, JWT validation, inactivity timeout, token refresh
├── models/                    # 11 ORM models (SQLAlchemy 2.0 mapped columns)
│   ├── user_model.py
│   ├── main_data_model.py
│   ├── identity_data_model.py
│   ├── inquiry_data_model.py
│   ├── upload_history_model.py
│   ├── upload_error_model.py
│   ├── login_activity_model.py
│   ├── password_reset_model.py
│   ├── customer_view_activity_model.py
│   ├── admin_activity_model.py
│   └── saved_filter_model.py
├── routers/                   # 7 route modules
│   ├── auth_router.py         # /auth/* (register, login, forgot/reset password, me)
│   ├── admin_router.py        # /admin/* (dashboard, users CRUD, audit logs)
│   ├── user_router.py         # /user/* (dashboard)
│   ├── upload_router.py       # /upload/* (file upload, progress polling, test page)
│   ├── customer_router.py     # /customers/* (search, detail, timeline, summary, export)
│   ├── chart_router.py        # /charts/global/* (income trend, bank distribution)
│   └── saved_filter_router.py # /filters (CRUD)
├── schemas/                   # 13 Pydantic request/response schemas
│   ├── user_schema.py
│   ├── customer_schema.py
│   ├── customer_summary_schema.py
│   ├── customer_timeline_schema.py
│   ├── customer_view_activity_schema.py
│   ├── chart_schema.py
│   ├── dashboard_schema.py
│   ├── login_activity_schema.py
│   ├── password_reset_schema.py
│   ├── saved_filter_schema.py
│   ├── upload_schema.py
│   ├── upload_error_schema.py
│   └── admin_activity_schema.py
├── services/                  # 11 service modules (business logic layer)
│   ├── auth_service.py        # User creation, authentication, token generation
│   ├── user_service.py        # Admin user CRUD with audit logging
│   ├── upload_service.py      # Multi-file upload, auto-detect, batch insert
│   ├── customer_service.py    # Search, detail, timeline, export, analytics
│   ├── dashboard_service.py   # Dashboard analytics with 60s TTL cache
│   ├── pdf_service.py         # ReportLab PDF generation
│   ├── password_reset_service.py
│   ├── login_activity_service.py
│   ├── customer_view_activity_service.py
│   ├── admin_activity_service.py
│   └── saved_filter_service.py
└── utils/
    └── masking.py             # PII masking (PAN, Aadhaar, phone, email, etc.)
alembic/
├── versions/                  # 16 migration files
├── env.py
└── script.py.mako
seed_admin.py                  # Initial admin user seeder (idempotent)
render.yaml                    # Render deployment blueprint
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `SECRET_KEY` | Yes | — | JWT signing secret |
| `ENV` | No | `dev` | Environment mode (`dev` or `prod`) |
| `DEBUG` | No | `False` | Enable SQL echo logging |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `30` | JWT token expiry in minutes |
| `CORS_ORIGINS` | No | `["http://localhost:3000"]` | JSON array of allowed origins |
| `RESET_LINK_BASE_URL` | No | `http://localhost:3000/reset-password` | Frontend reset page URL |
| `SMTP_HOST` | No | — | SMTP server (required in prod for password reset emails) |
| `SMTP_PORT` | No | `587` | SMTP port |
| `SMTP_USERNAME` | No | — | SMTP login |
| `SMTP_PASSWORD` | No | — | SMTP password |
| `SMTP_FROM_EMAIL` | No | — | Sender email address |
| `SMTP_USE_TLS` | No | `True` | Enable STARTTLS |
| `ADMIN_USERNAME` | No | — | Seed admin username (used by `seed_admin.py`) |
| `ADMIN_EMAIL` | No | — | Seed admin email |
| `ADMIN_PASSWORD` | No | — | Seed admin password |

> **Dev vs Prod mode**: When `ENV=dev`, the forgot-password endpoint returns the reset link in the API response for demo purposes. When `ENV=prod`, the link is sent via SMTP email only.

---

## Deployment

The project includes a `render.yaml` for one-click deployment on [Render](https://render.com):

```bash
# Build command (runs on every deploy)
pip install -r requirements.txt && alembic upgrade head && python seed_admin.py

# Start command
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

### Startup Behavior

On boot, the app automatically:
- Marks any uploads stuck in `processing` status as `failed`
- Purges orphan data rows (main, identity, inquiry, error) from interrupted uploads

### Database Connection Pool

- Pool size: 10 connections
- Max overflow: 20 additional connections
- Pool timeout: 30 seconds
- Connection recycle: 1800 seconds (30 min)
- Pre-ping enabled for stale connection detection

