# CIBIL Bureau Dashboard — Backend

FastAPI backend for ingesting, querying, and reporting on CIBIL credit bureau data. Handles multi-file pipe-separated uploads with auto-detection, historical snapshots, customer search with identity filters, analytics, PDF/CSV export, and full audit logging — all behind JWT auth with RBAC.

**Live**: https://cibil-backend-yx2e.onrender.com

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | FastAPI 0.135.1 |
| Database | PostgreSQL (SQLAlchemy 2.0, Alembic migrations) |
| Auth | JWT (HS256) + bcrypt password hashing |
| PDF | ReportLab 4.2.5 |
| Rate Limiting | SlowAPI (per-IP) |
| Server | Uvicorn 0.41.0 |
| Deployment | Render (free tier) |
| Python | 3.12+ |

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
# Edit .env with your DATABASE_URL and SECRET_KEY

# Run migrations
alembic upgrade head

# Seed initial admin user
python seed_admin.py

# Start server
uvicorn app.main:app --reload
```

## API Documentation

Once running, interactive docs are available at:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## API Endpoints

### Health

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | None | Health check with DB connectivity verification |

### Authentication

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/register` | None | Register a new user |
| POST | `/auth/login` | None | Login, returns JWT token (rate-limited: 5/min) |
| POST | `/auth/forgot-password` | None | Initiate password reset flow (rate-limited: 3/min) |
| POST | `/auth/reset-password` | None | Complete password reset with token |
| GET | `/auth/me` | Any | Get current user profile |

### File Upload

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/upload/files` | Admin | Upload N pipe-separated .txt files (async background processing) |
| GET | `/upload/status/{upload_id}` | Any | Poll upload progress (current/total rows, status) |

### Customer Search & Detail

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/customers/search` | Any | Search customers with filters + keyset/offset pagination |
| GET | `/customers/{id}` | Any | Full joined main + identity records (all snapshots) |
| GET | `/customers/{id}/timeline` | Admin/User | Historical timeline across all snapshots |
| GET | `/customers/{id}/summary` | Admin/User | Analytics summary (income, bank, identity, timeline) |

**Search filters**: `customer_id`, `pan`, `phone`, `acct_key`, `bank_type`, `occup_status_cd`, `income_min`, `income_max`, `rpt_dt_from`, `rpt_dt_to`

### Charts

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/customers/{id}/income-trend` | Admin/User | Chart-ready income time series |
| GET | `/customers/{id}/bank-trend` | Admin/User | Chart-ready bank type changes |
| GET | `/charts/global/income-trend` | Admin/User | Global avg income by report date (filterable) |
| GET | `/charts/global/bank-distribution` | Admin/User | Global bank type distribution (filterable) |

### Export

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/customers/export/csv` | Any | Streaming CSV export (same filters as search) |
| GET | `/customers/{id}/report/pdf` | Admin/User | Bureau-style PDF report download |

### Dashboard & Admin

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/user/dashboard` | Any | User dashboard analytics |
| GET | `/admin/dashboard` | Admin | Admin dashboard analytics |
| GET | `/admin/users` | Admin | List all users |
| POST | `/admin/users` | Admin | Create user |
| PATCH | `/admin/users/{user_id}` | Admin | Update user |
| DELETE | `/admin/users/{user_id}` | Admin | Delete user |
| GET | `/admin/login-activity` | Admin | Recent login attempts |
| GET | `/admin/customer-view-activity` | Admin | Customer view audit log |
| GET | `/admin/upload-errors` | Admin | Row-level upload errors |
| GET | `/admin/admin-activity` | Admin | Admin action audit trail |

### Saved Filters

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/filters` | Any | Save a filter preset |
| GET | `/filters` | Any | List current user's saved filters |
| DELETE | `/filters/{filter_id}` | Any | Delete a saved filter |

### Upload History

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/uploads/history` | Any | Paginated upload history (limit/offset) |

---

## Upload System

The upload endpoint accepts N pipe-separated `.txt` files and auto-classifies each by its header row:

| File Type | Detection Header | Data Stored |
|-----------|-----------------|-------------|
| **Account** (required) | `ACCT_KEY` | main_data (income, bank_type, rpt_dt, etc.) |
| **Credit Score** | `SCORE_V3` or `CUST_ID` (≤3 cols) | Enriches main_data.credit_score |
| **Identity Docs** | `PAN`, `PASSPORT`, or `VOTER_ID` | identity_data (PAN, UID, passport, etc.) |
| **Phone** | `PHONE` (without `EMAIL`) | identity_data.phone |
| **Personal** | `FULL_NAME` or `DOB` + `GENDER` | main_data (full_name, dob, gender) |
| **Email** | `EMAIL` (without `PHONE`) | identity_data.email |
| **Address** | `ADDRESS` or `PINCODE` | identity_data (address, pincode) |
| **Inquiry** | `INQ_PURP_CD` | inquiry_data table |

Upload is processed asynchronously in background. Poll `/upload/status/{id}` for progress.

### Generating Test Data

```bash
python scripts/generate_test_data.py          # outputs to ./test_data/
python scripts/generate_test_data.py /tmp/out  # custom output dir
```

Generates 8 files (5 customers) covering every file type above.

---

## Database Schema

11 tables managed via Alembic migrations:

| Table | Purpose |
|-------|---------|
| `users` | User accounts with role (admin/user) |
| `main_data` | Core account-level CIBIL data per snapshot |
| `identity_data` | Identity documents + contact info per snapshot |
| `inquiry_data` | Credit inquiry records per snapshot |
| `upload_history` | Upload metadata, status, progress tracking |
| `upload_errors` | Row-level error logging for failed rows |
| `login_activity` | Login attempt tracking (success/failure) |
| `password_reset_tokens` | Time-limited password reset tokens |
| `customer_view_activity` | Audit log for customer record views |
| `admin_activity` | Admin action audit trail |
| `saved_filters` | User-saved search filter presets |

### Snapshot Model

Every upload creates a **snapshot** (upload_history.id). All records from one upload share the same `snapshot_id`. Search endpoints query only the latest successful snapshot. Timeline/detail endpoints span all snapshots for historical data.

### Key Indexes

- `main_data`: composite (customer_id, snapshot_id), acct_key, occup_status_cd, rpt_dt
- `identity_data`: composite (customer_id, snapshot_id), pan, phone
- `inquiry_data`: composite (customer_id, snapshot_id)

---

## Security

### Authentication & Authorization
- JWT tokens (HS256) with configurable expiry
- Sliding-window token refresh via `X-New-Token` response header
- Role-based access control: `admin` and `user` roles
- bcrypt password hashing

### Rate Limiting
- `/auth/login`: 5 requests/minute per IP
- `/auth/forgot-password`: 3 requests/minute per IP

### PII Masking

All identity fields are masked before leaving the service layer — never stored masked:

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
├── main.py                 # FastAPI app, CORS, lifespan (stuck upload cleanup)
├── core/
│   ├── config.py           # Pydantic Settings (env vars)
│   ├── security.py         # JWT creation/validation + bcrypt
│   └── rate_limit.py       # SlowAPI limiter config
├── db/
│   ├── base.py             # SQLAlchemy DeclarativeBase
│   └── database.py         # Engine, session pool, get_db dependency
├── dependencies/
│   └── role_checker.py     # RBAC guards, JWT validation, token refresh
├── models/                 # 11 ORM models
│   ├── main_data_model.py
│   ├── identity_data_model.py
│   ├── inquiry_data_model.py
│   ├── upload_history_model.py
│   ├── upload_error_model.py
│   ├── user_model.py
│   ├── login_activity_model.py
│   ├── password_reset_model.py
│   ├── customer_view_activity_model.py
│   ├── admin_activity_model.py
│   └── saved_filter_model.py
├── routers/                # 7 route modules
│   ├── auth_router.py
│   ├── admin_router.py
│   ├── user_router.py
│   ├── upload_router.py
│   ├── customer_router.py
│   ├── chart_router.py
│   └── saved_filter_router.py
├── schemas/                # Pydantic request/response schemas
├── services/               # 11 service modules
│   ├── upload_service.py       # Multi-file upload, auto-detect, batch insert
│   ├── customer_service.py     # Search, detail, timeline, export, analytics
│   ├── pdf_service.py          # ReportLab PDF generation
│   ├── dashboard_service.py    # Dashboard analytics with 60s TTL cache
│   ├── auth_service.py
│   ├── user_service.py
│   ├── password_reset_service.py
│   ├── login_activity_service.py
│   ├── customer_view_activity_service.py
│   ├── admin_activity_service.py
│   └── saved_filter_service.py
└── utils/
    └── masking.py          # PII masking (PAN, Aadhaar, phone, email, etc.)
alembic/
├── versions/               # 16 migration files
├── env.py
└── script.py.mako
docs/                       # Detailed engineering documentation
scripts/
└── generate_test_data.py   # Test data generator (8 file types)
seed_admin.py               # Initial admin user seeder
render.yaml                 # Render deployment blueprint
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `SECRET_KEY` | Yes | — | JWT signing secret |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `30` | JWT token expiry |
| `DEBUG` | No | `False` | Enable SQL echo + dev features |
| `CORS_ORIGINS` | No | `["http://localhost:3000"]` | JSON array of allowed origins |
| `SMTP_HOST` | No | — | SMTP server for password reset emails |
| `SMTP_PORT` | No | `587` | SMTP port |
| `SMTP_USERNAME` | No | — | SMTP login |
| `SMTP_PASSWORD` | No | — | SMTP password |
| `SMTP_FROM_EMAIL` | No | — | Sender email address |
| `RESET_LINK_BASE_URL` | No | `http://localhost:3000/reset-password` | Frontend reset page URL |
| `ADMIN_USERNAME` | No | — | Seed admin username (used by seed_admin.py) |
| `ADMIN_EMAIL` | No | — | Seed admin email |
| `ADMIN_PASSWORD` | No | — | Seed admin password |

## Deployment

The project includes a `render.yaml` for one-click deployment on [Render](https://render.com).

```bash
# Build command (runs on every deploy)
pip install -r requirements.txt && alembic upgrade head && python seed_admin.py

# Start command
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

### Startup Behavior

On boot, the app automatically:
- Marks any uploads stuck in `processing` status as `failed`
- Purges orphan data rows from interrupted uploads

## Detailed Documentation

See the [docs/](docs/) folder for in-depth engineering documentation:
- Architecture Overview
- Data Flow
- Database Schema
- API Documentation
- Service Layer
- Analytics Engine
- PDF Report Flow
- Security & Masking
- Performance & Optimization
- Edge Cases
- Logging & Observability
- Future Improvements
