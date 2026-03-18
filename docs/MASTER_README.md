# CIBIL Dashboard — Backend Documentation

## What This Is

This is the complete internal engineering documentation for the CIBIL Dashboard backend. It covers architecture, data flow, database design, APIs, services, analytics, PDF generation, security, performance, edge cases, logging, and future roadmap.

**Goal**: A new developer should be able to fully understand, maintain, and extend the backend by reading these documents — without having to read all the source code.

---

## Quick Facts

| Item | Value |
|------|-------|
| **Framework** | FastAPI 0.135.1 |
| **Database** | PostgreSQL (SQLAlchemy 2.0, Alembic migrations) |
| **Auth** | JWT (HS256) with bcrypt password hashing |
| **PDF** | ReportLab 4.2.5 |
| **Python** | 3.12+ (uses `str \| None` syntax) |
| **Server** | Uvicorn 0.41.0 |

---

## Documentation Index

### System Architecture

| # | Document | What You'll Learn |
|---|----------|-------------------|
| 1 | [Architecture Overview](./ARCHITECTURE_OVERVIEW.md) | Tech stack, directory structure, layered design, configuration, database strategy, key design decisions |
| 2 | [Data Flow](./DATA_FLOW.md) | How data moves through the system — upload → DB → services → API → client. Includes search, detail, timeline, analytics, CSV export, and PDF flows with diagrams |
| 3 | [Database Schema](./DATABASE_SCHEMA.md) | All 9 tables with column details, indexes, relationships, migration history, and design rationale for storing income/dates as strings |

### API & Services

| # | Document | What You'll Learn |
|---|----------|-------------------|
| 4 | [API Documentation](./API_DOCUMENTATION.md) | Every endpoint with request/response examples, auth requirements, query parameters, error codes, and the sliding-window token refresh mechanism |
| 5 | [Service Layer Explained](./SERVICE_LAYER_EXPLAINED.md) | All 10 services in depth — customer_service (1000 lines), upload_service, auth, users, dashboard, PDF, audit logging, password reset, saved filters. Includes helper function documentation |
| 6 | [Analytics Engine](./ANALYTICS_ENGINE.md) | The five analytics sections (profile, income, bank, identity, timeline), caching strategy, income trend/volatility computation, strong identity definition, activity status logic |

### Specialized Systems

| # | Document | What You'll Learn |
|---|----------|-------------------|
| 7 | [PDF Report Flow](./PDF_REPORT_FLOW.md) | End-to-end PDF generation — data preparation, ReportLab layout, sections, styling, and how identity masking is guaranteed upstream |
| 8 | [Security and Masking](./SECURITY_AND_MASKING.md) | JWT auth, bcrypt 72-byte handling, RBAC, sliding-window refresh, identity masking rules (6 field types), password reset security, audit logging, admin self-protection |

### Operations

| # | Document | What You'll Learn |
|---|----------|-------------------|
| 9 | [Performance and Optimization](./PERFORMANCE_AND_OPTIMIZATION.md) | Database indexes, keyset pagination, bulk insert strategy, streaming export, parse caching, what is NOT optimized (honest assessment) |
| 10 | [Edge Cases and Handling](./EDGE_CASES_AND_HANDLING.md) | 17 documented edge cases — missing income, invalid dates, single snapshot, empty identity, missing CUSTOMER_ID, bulk insert failures, short value masking, and more |
| 11 | [Logging and Observability](./LOGGING_AND_OBSERVABILITY.md) | What is logged (and at which level), what is NOT logged (and why), structured logging patterns, SQL echo, database audit trail, observability gaps |
| 12 | [Future Improvements](./FUTURE_IMPROVEMENTS.md) | 18 actionable improvements prioritized by impact — caching, CORS, async DB, rate limiting, testing, email integration, and what features are explicitly not implemented |

---

## Reading Order

**If you're new to the project**, read in this order:

1. **Architecture Overview** — understand the shape of the system
2. **Database Schema** — understand the data model
3. **Data Flow** — understand how data moves
4. **API Documentation** — understand what the system exposes
5. **Service Layer Explained** — understand the business logic
6. Everything else as needed

**If you're debugging a specific issue**, jump directly to the relevant document:

- Upload failing? → [Data Flow](./DATA_FLOW.md) + [Edge Cases](./EDGE_CASES_AND_HANDLING.md)
- Analytics wrong? → [Analytics Engine](./ANALYTICS_ENGINE.md)
- Masking issue? → [Security and Masking](./SECURITY_AND_MASKING.md)
- Performance? → [Performance and Optimization](./PERFORMANCE_AND_OPTIMIZATION.md)
- PDF broken? → [PDF Report Flow](./PDF_REPORT_FLOW.md)

---

## Key Files Quick Reference

| File | Lines | Role |
|------|-------|------|
| `app/main.py` | ~37 | FastAPI entry point, router mounting |
| `app/services/customer_service.py` | ~1000 | Core business logic — search, detail, timeline, analytics, export |
| `app/services/upload_service.py` | ~300 | File upload, parsing, bulk insert |
| `app/services/pdf_service.py` | ~260 | PDF report generation |
| `app/utils/masking.py` | ~95 | Identity field masking utilities |
| `app/dependencies/role_checker.py` | ~136 | JWT validation, RBAC, token refresh |
| `app/core/security.py` | ~92 | Password hashing, JWT create/decode |
| `app/core/config.py` | ~55 | Pydantic Settings (env vars) |

---

## Running the Project

### Prerequisites

- Python 3.12+
- PostgreSQL
- Virtual environment recommended

### Setup

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your DATABASE_URL and SECRET_KEY

# Run migrations
alembic upgrade head

# Start the server
uvicorn app.main:app --reload
```

### Generate Test Data

```bash
python generate_cibil_test_data.py
# Creates main_data.txt (200K rows) and identity_data.txt (120K rows)
# Upload via POST /upload/files
```

### API Docs

FastAPI auto-generates interactive API documentation:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
