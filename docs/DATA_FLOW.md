# Data Flow

## Overview

Data flows through the system in a single direction: **Upload → Database → Services → APIs → Client (JSON/CSV/PDF)**. This document traces the exact path data takes at each stage.

---

## 1. Upload Flow (Data Ingestion)

### Entry Point

`POST /upload/files` → `app/routers/upload_router.py` → `app/services/upload_service.py`

### Step-by-Step

```
Admin uploads two .txt files (pipe-separated)
        │
        ▼
upload_router.py validates file extensions (.txt only)
        │
        ▼
process_upload_files() orchestrates the entire ingestion
        │
        ├── Step 1: Create UploadHistory record → commit to get snapshot_id (PK)
        │
        ├── Step 2: _build_identity_map() reads identity file into memory
        │           Creates dict[customer_id → identity_row]
        │
        ├── Step 3: Reset main file pointer, open DictReader
        │
        ├── Step 4: Iterate main file rows:
        │           ├── Extract CUSTOMER_ID (skip if missing)
        │           ├── Look up identity from in-memory map
        │           ├── Normalize empty values to None
        │           ├── Buffer into main_batch and identity_batch
        │           └── Flush every 10,000 rows (BATCH_SIZE)
        │
        ├── Step 5: flush_batches() does bulk_insert_mappings
        │           ├── Uses begin_nested() for savepoint safety
        │           ├── On failure: logs errors, records UploadError rows
        │           └── Clears buffers after each flush
        │
        └── Step 6: Update UploadHistory with final counts and status
                    ├── "success"  — all rows inserted
                    ├── "partial"  — some succeeded, some failed
                    └── "failed"   — zero rows inserted
```

### File Format Expected

**Main file** (`main_data.txt`):
```
ACCT_KEY|CUSTOMER_ID|INCOME|INCOME_FREQ|OCCUP_STATUS_CD|RPT_DT|BANK_TYPE
100000001|9001234567|75000|1|SAL|2025-01-31|PSU
```

**Identity file** (`identity_data.txt`):
```
CUSTOMER_ID|PAN|PASSPORT|VOTER_ID|UID|RATION_CARD|DRIVING_LICENSE
9001234567|ABCDE1234F|A1234567|AB1234567|123456789012|RC0000000001|DL000000000001
```

### Join Strategy

The join between main and identity data happens **in-memory** during upload. The identity file is loaded entirely into a `dict[str, dict[str, str]]` keyed by `CUSTOMER_ID`. As each main file row is processed, the corresponding identity record (if any) is looked up and inserted alongside.

**Trade-off**: This requires the identity file to fit in memory. The codebase notes this is acceptable for current dataset sizes but may need revisiting for multi-million-row identity files.

### Snapshot Model

Each upload creates a new snapshot. The `UploadHistory.id` (auto-increment primary key) becomes the `snapshot_id` for all `MainData` and `IdentityData` rows in that upload. This means:

- Old data is never overwritten
- Multiple snapshots can coexist
- Queries can target a specific snapshot or the latest one

---

## 2. Search Flow (Data Retrieval)

### Entry Point

`GET /customers/search` → `search_customers()` in `customer_service.py`

### Flow

```
Client sends search query (filters, pagination)
        │
        ▼
Router validates inputs (income_min <= income_max, date range)
        │
        ▼
Service gets latest snapshot_id via _get_latest_snapshot_id()
        │
        ▼
Builds SQLAlchemy query:
  - SELECT from MainData OUTER JOIN IdentityData
  - WHERE snapshot_id = latest_snapshot
  - Apply dynamic filters via _apply_customer_search_filters()
        │
        ▼
Pagination:
  ├── Keyset: WHERE customer_id > last_customer_id LIMIT page_size
  └── Legacy: OFFSET (page-1)*page_size LIMIT page_size
        │
        ▼
Results mapped to CustomerSearchResponse
  - PAN is masked via mask_pan() before being added to response
        │
        ▼
Returns CustomerSearchPage { data: [...], next_cursor: "..." }
```

### Filter Support

The `_apply_customer_search_filters()` function applies these optional filters:

| Filter | Column | Method |
|--------|--------|--------|
| `customer_id` | `MainData.customer_id` | Exact match |
| `pan` | `IdentityData.pan` | Exact match |
| `acct_key` | `MainData.acct_key` | Exact match |
| `bank_type` | `MainData.bank_type` | Exact match |
| `occup_status_cd` | `MainData.occup_status_cd` | Exact match |
| `income_min` | `MainData.income` (cast to Integer) | >= |
| `income_max` | `MainData.income` (cast to Integer) | <= |
| `rpt_dt_from` | `MainData.rpt_dt` | >= (string comparison) |
| `rpt_dt_to` | `MainData.rpt_dt` | <= (string comparison) |

This filter function is shared between search and CSV export to guarantee consistent behavior.

---

## 3. Customer Detail Flow

### Entry Point

`GET /customers/{customer_id}` → `get_customer_details()`

### Flow

```
Service queries MainData LEFT JOIN IdentityData
  - WHERE MainData.customer_id = customer_id
  - Returns ALL snapshots (not just latest)
        │
        ▼
For each row:
  1. Validate MainData → MainDataResponse
  2. Validate IdentityData → IdentityDataResponse (if present)
  3. Apply _apply_identity_masking() on identity response
  4. Bundle into CustomerDetailResponse
        │
        ▼
Router:
  - If no results → HTTP 404
  - Logs customer view via log_customer_view() (in nested transaction)
  - Returns list of CustomerDetailResponse
```

---

## 4. Timeline Flow

### Entry Point

`GET /customers/{customer_id}/timeline` → `get_customer_timeline()`

### Flow

```
Service builds three-table join:
  MainData JOIN UploadHistory ON snapshot_id
  LEFT JOIN IdentityData ON (customer_id, snapshot_id)
        │
        ▼
Ordered by:
  1. rpt_dt ASC (NULL/empty pushed to end via CASE expression)
  2. snapshot_id ASC
        │
        ▼
Each row → CustomerTimelineEntry
  - Includes main fields + identity fields
  - _apply_identity_masking() applied to each entry
        │
        ▼
Returns CustomerTimelineResponse { customer_id, timeline: [...] }
```

---

## 5. Analytics Summary Flow

### Entry Point

`GET /customers/{customer_id}/summary` → `get_customer_summary_analytics()`

### Flow

```
Calls get_customer_details() → sorted by _detail_sort_key
Calls get_customer_timeline() → uses timeline entries
        │
        ▼
Builds 5 analytics sections:
  ├── _build_profile()           → total_accounts, latest_income, dates
  ├── _build_income_analysis()   → avg/max/min, trend, volatility
  ├── _build_bank_analysis()     → unique types, changes, most frequent
  ├── _build_identity_analysis() → types present, strong identity check
  └── _build_timeline_insights() → span days, activity status
        │
        ▼
_strip_none_values() removes all None entries from response
        │
        ▼
Returns CustomerSummaryAnalyticsResponse
```

---

## 6. Chart Trend Flow

### Entry Points

- `GET /customers/{customer_id}/income-trend` → `get_income_trend()`
- `GET /customers/{customer_id}/bank-trend` → `get_bank_trend()`

### Flow

```
Query MainData for the customer, ordered by rpt_dt ASC, snapshot_id ASC
        │
        ▼
Income trend:
  - Parse each income value
  - Deduplicate consecutive identical (x, y) pairs
  - Return list of ChartPoint { x: rpt_dt, y: parsed_income }

Bank trend:
  - Track bank_type changes
  - Only emit a point when bank_type differs from previous
  - Return list of ChartPoint { x: rpt_dt, y: bank_type }
```

---

## 7. CSV Export Flow

### Entry Point

`GET /customers/export/csv` → `stream_customers_csv()`

### Flow

```
Same filters as search (shared via _apply_customer_search_filters)
        │
        ▼
iter_customers_for_export():
  - Queries latest snapshot only
  - Uses yield_per(1000) for memory-efficient streaming
  - Masks identity fields before yielding
        │
        ▼
stream_customers_csv():
  - Writes CSV header row
  - Yields each data row as a CSV-formatted string chunk
  - Uses StringIO buffer, cleared after each row
        │
        ▼
Router returns StreamingResponse:
  - media_type: "text/csv"
  - Content-Disposition: attachment; filename="customers_export.csv"
```

---

## 8. PDF Report Flow

### Entry Point

`GET /customers/{customer_id}/report/pdf` → `get_customer_report_data()` → `generate_customer_pdf()`

### Flow

```
get_customer_report_data():
  - Calls get_customer_details() and get_customer_timeline()
  - Extracts overview (latest snapshot)
  - Finds latest non-null identity
  - Builds flat dict structure for PDF consumption
        │
        ▼
generate_customer_pdf() in pdf_service.py:
  - Uses ReportLab's SimpleDocTemplate (A4)
  - Renders: Header → Overview → Accounts table → Identity → Timeline table
  - Returns raw PDF bytes
        │
        ▼
Router wraps in StreamingResponse:
  - media_type: "application/pdf"
  - Content-Disposition: attachment; filename="customer_{id}_report.pdf"
```

---

## 9. Dashboard Flow

### Entry Points

- `GET /admin/dashboard` (admin only)
- `GET /user/dashboard` (admin or user)

Both call `dashboard_service.get_dashboard_data()`.

### Flow

```
Determine latest snapshot via func.max(MainData.snapshot_id)
        │
        ▼
Run aggregate queries on latest snapshot:
  ├── COUNT(DISTINCT customer_id) → total_customers
  ├── COUNT(id) → total_records
  ├── AVG(NULLIF(income, '') CAST Float) → average_income
  ├── GROUP BY bank_type, COUNT → bank_distribution
  └── TOP 5 UploadHistory → recent_uploads
        │
        ▼
Returns DashboardResponse { summary, bank_distribution, recent_uploads }
```

---

## Data Flow Summary Diagram

```
  ┌──────────────┐       ┌──────────────────┐
  │  .txt Files  │──────▶│  Upload Service   │
  │ (pipe-sep)   │       │  (parse + join)   │
  └──────────────┘       └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │   PostgreSQL DB   │
                         │  main_data        │
                         │  identity_data    │
                         │  upload_history   │
                         │  upload_errors    │
                         └────────┬─────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
     ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
     │ Customer Svc   │  │ Dashboard Svc  │  │ PDF Service    │
     │ (search,detail │  │ (aggregates)   │  │ (ReportLab)    │
     │  timeline,     │  └────────┬───────┘  └────────┬───────┘
     │  analytics,    │           │                    │
     │  CSV export)   │           │                    │
     └────────┬───────┘           │                    │
              │                   │                    │
              ▼                   ▼                    ▼
     ┌─────────────────────────────────────────────────────┐
     │              API Response Layer                      │
     │  (JSON, StreamingResponse CSV, StreamingResponse PDF)│
     │  All identity fields masked before response          │
     └─────────────────────────────────────────────────────┘
```
