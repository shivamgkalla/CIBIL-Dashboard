# CIBIL Bureau Dashboard — Backend

FastAPI backend for ingesting, querying, and reporting on CIBIL credit bureau data. Handles pipe-separated file uploads, historical snapshots, customer search, analytics, PDF/CSV export, and audit logging — all behind JWT auth with RBAC.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | FastAPI 0.135.1 |
| Database | PostgreSQL (SQLAlchemy 2.0, Alembic migrations) |
| Auth | JWT (HS256) + bcrypt password hashing |
| PDF | ReportLab 4.2.5 |
| Server | Uvicorn 0.41.0 |
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

## Project Structure

```
app/
├── main.py                 # FastAPI entry point, CORS, router mounting
├── core/
│   ├── config.py           # Pydantic Settings (env vars)
│   └── security.py         # JWT + bcrypt utilities
├── db/
│   ├── base.py             # SQLAlchemy DeclarativeBase
│   └── database.py         # Engine, session, get_db dependency
├── dependencies/
│   └── role_checker.py     # RBAC, JWT validation, sliding-window refresh
├── models/                 # 9 ORM models
├── routers/                # 6 route modules
├── schemas/                # Pydantic request/response schemas
├── services/               # Business logic (10 service modules)
└── utils/
    └── masking.py          # Identity field masking (PAN, Aadhaar, etc.)
```

## Key Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/register` | Optional | Register user |
| POST | `/auth/login` | None | Get JWT token |
| POST | `/auth/forgot-password` | None | Initiate password reset |
| POST | `/auth/reset-password` | None | Complete password reset |
| GET | `/admin/dashboard` | Admin | Aggregated analytics |
| GET | `/user/dashboard` | Any | Dashboard (shared) |
| POST | `/upload/files` | Admin | Upload CIBIL data files |
| GET | `/customers/search` | Any | Search with filters + pagination |
| GET | `/customers/{id}` | Any | Customer detail (all snapshots) |
| GET | `/customers/{id}/timeline` | Any | Historical timeline |
| GET | `/customers/{id}/summary` | Any | Analytics summary |
| GET | `/customers/{id}/income-trend` | Any | Chart-ready income data |
| GET | `/customers/{id}/bank-trend` | Any | Chart-ready bank type data |
| GET | `/customers/export/csv` | Any | Streaming CSV export |
| GET | `/customers/{id}/report/pdf` | Any | PDF report download |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `SECRET_KEY` | Yes | — | JWT signing secret |
| `DEBUG` | No | `False` | Enable SQL echo + dev features |
| `CORS_ORIGINS` | No | `["http://localhost:3000"]` | JSON array of allowed origins |
| `SMTP_HOST` | No | — | SMTP server for password reset emails |
| `SMTP_PORT` | No | `587` | SMTP port |
| `SMTP_USERNAME` | No | — | SMTP login |
| `SMTP_PASSWORD` | No | — | SMTP password |
| `SMTP_FROM_EMAIL` | No | — | Sender email address |
| `RESET_LINK_BASE_URL` | No | `http://localhost:3000/reset-password` | Frontend reset page URL |

## Deployment

The project includes a `render.yaml` for one-click deployment on [Render](https://render.com). See `render.yaml` for the full blueprint.

```bash
# Build command (runs on deploy)
pip install -r requirements.txt && alembic upgrade head

# Start command
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

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
