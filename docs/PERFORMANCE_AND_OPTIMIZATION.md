# Performance and Optimization

## Overview

The system is designed to handle large CIBIL datasets (200K+ rows per upload, millions of rows across snapshots). Performance optimizations exist at the database, query, ingestion, and application layers.

---

## Database-Level Optimizations

### Strategic Indexing

The schema uses both single-column and composite indexes, chosen based on actual query patterns:

**`main_data` table indexes**:

| Index | Columns | Used By |
|-------|---------|---------|
| `ix_main_data_customer_snapshot` | `(customer_id, snapshot_id)` | Customer detail, timeline — the primary lookup pattern |
| `ix_main_data_occup_status_cd` | `occup_status_cd` | Search filter |
| `ix_main_data_rpt_dt` | `rpt_dt` | Date range filtering |
| PK index on `id` | `id` | Standard |
| Index on `acct_key` | `acct_key` | Search filter |
| Index on `customer_id` | `customer_id` | All customer queries |
| Index on `snapshot_id` | `snapshot_id` | Snapshot-scoped queries |

**`identity_data` table indexes**:

| Index | Columns | Used By |
|-------|---------|---------|
| `ix_identity_data_customer_snapshot` | `(customer_id, snapshot_id)` | JOIN with main_data |
| Index on `customer_id` | `customer_id` | Standalone lookups |
| Index on `pan` | `pan` | PAN-based search filter |
| Index on `snapshot_id` | `snapshot_id` | Snapshot-scoped queries |

**Audit table indexes**:

| Table | Index | Purpose |
|-------|-------|---------|
| `login_activity` | `(email, login_time)` composite | Time-scoped email queries |
| `customer_view_activity` | `(user_id, viewed_at)` composite | User-specific audit queries |
| `upload_errors` | `upload_id` | Error lookup by upload |

### Connection Pool Health

```python
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=settings.DEBUG,
)
```

`pool_pre_ping=True` ensures dead connections are detected and recycled before use. This prevents the application from failing when PostgreSQL drops idle connections.

`echo=settings.DEBUG` enables SQL logging only in debug mode, avoiding the performance overhead of logging every query in production.

---

## Query-Level Optimizations

### Latest Snapshot Determination

```python
def _get_latest_snapshot_id(db: Session) -> int | None:
    return db.query(func.max(UploadHistory.id)).select_from(UploadHistory).scalar()
```

This uses a simple `MAX(id)` query on the `upload_history` table (which has far fewer rows than `main_data`) rather than scanning `main_data.snapshot_id`. The primary key index makes this essentially instant.

### Search: Selective Column Projection

The search query only selects the columns needed for the response:

```python
db.query(
    MainData.customer_id,
    MainData.acct_key,
    MainData.bank_type,
    MainData.income,
    MainData.rpt_dt,
    IdentityData.pan,
)
```

This avoids loading full ORM objects, reducing memory usage and network transfer for search results.

### Keyset Pagination

For large datasets, keyset (cursor-based) pagination is available:

```python
if last_customer_id is not None:
    query = query.filter(MainData.customer_id > last_customer_id)
    rows = query.order_by(MainData.customer_id).limit(page_size).all()
```

**Why this matters**: Traditional OFFSET pagination degrades as the offset increases — `OFFSET 100000` requires the database to scan and skip 100,000 rows. Keyset pagination using `WHERE customer_id > cursor` leverages the index and performs consistently regardless of how deep into the dataset you are.

Both pagination modes are supported: keyset for performance-sensitive frontends, offset for backward compatibility.

### Dashboard: Aggregate Functions Only

```python
total_customers = db.query(func.count(func.distinct(MainData.customer_id)))
    .filter(MainData.snapshot_id == latest_snapshot)
    .scalar()

average_income = db.query(
    func.avg(cast(func.nullif(MainData.income, ""), Float))
).filter(MainData.snapshot_id == latest_snapshot).scalar()
```

Dashboard queries use SQL aggregate functions exclusively — no ORM objects are loaded. This keeps memory constant regardless of dataset size.

The `NULLIF(income, '')` trick converts empty strings to NULL before casting to Float, avoiding type errors on empty income fields.

### Timeline: CASE-based Sorting

```python
def _rpt_dt_sort_key():
    return case(
        (MainData.rpt_dt.is_(None), literal("9999-12-31")),
        (MainData.rpt_dt == "", literal("9999-12-31")),
        else_=MainData.rpt_dt,
    )
```

This pushes NULL/empty dates to the end of results directly in SQL, avoiding post-query sorting in Python.

---

## Ingestion Optimizations

### Bulk Insert Mappings

```python
db.bulk_insert_mappings(MainData, main_batch)
db.bulk_insert_mappings(IdentityData, identity_batch)
```

`bulk_insert_mappings` bypasses the ORM's per-object overhead (identity map tracking, event hooks, etc.) and generates a single multi-row INSERT statement. For a 200K-row file, this is orders of magnitude faster than individual `db.add()` calls.

### Batch Size

```python
BATCH_SIZE = 10_000
```

Rows are accumulated in memory and flushed every 10,000 rows. This balances:
- **Memory**: 10K dicts is manageable (a few MB)
- **Transaction size**: Large enough to amortize commit overhead, small enough to limit rollback scope
- **Insert efficiency**: Multi-row INSERTs perform best at this scale

### Savepoint Safety

```python
with db.begin_nested():
    db.bulk_insert_mappings(MainData, main_batch)
    db.bulk_insert_mappings(IdentityData, identity_batch)
    db.flush()
```

`begin_nested()` creates a PostgreSQL SAVEPOINT. If a batch fails (e.g., constraint violation), only that batch is rolled back — all previously successful batches remain committed. This prevents a single bad row near the end of a 200K-row file from invalidating the entire upload.

### Streaming File Read

```python
def _iter_decoded_lines(file: UploadFile) -> Iterable[str]:
    def _line_iterator(binary: BinaryIO) -> Iterable[bytes]:
        while True:
            line = binary.readline()
            if not line:
                break
            yield line
    for raw_line in _line_iterator(file.file):
        yield raw_line.decode("utf-8", errors="replace")
```

Files are read line-by-line from the `SpooledTemporaryFile`, never fully loaded into memory. Combined with `csv.DictReader`, this allows processing files larger than available RAM (though the identity map is still loaded entirely).

### Single Final Commit

```python
# After all batches are flushed:
history.records_inserted = records_inserted
history.records_failed = records_failed
history.status = status
db.commit()
```

There is only one `COMMIT` at the end of the entire upload (aside from the initial UploadHistory creation). This minimizes transaction overhead and ensures the status update and data insertion are atomically consistent.

---

## Application-Level Optimizations

### Income Parse Caching

In `get_customer_summary_analytics()`, income values are parsed exactly once and stored in an indexed cache:

```python
income_cache_by_idx: list[int | float | None] = []
for item in sorted_details:
    raw_income = _norm_str(item.main_data.income)
    parsed = _parse_income(raw_income) if raw_income else None
    income_cache_by_idx.append(parsed)
```

Without this cache, `_parse_income()` would be called multiple times for the same value across the profile, income analysis, and trend computation — wasteful for large datasets.

### Report Date Parse Caching

Same pattern for report dates:

```python
rpt_dt_cache: list[datetime | None] = []
for entry in timeline:
    parsed_dt = _safe_parse_rpt_dt(raw_rpt_dt) if raw_rpt_dt else None
    rpt_dt_cache.append(parsed_dt)
```

### Sorting Reuse

Details are sorted once via `sorted(details, key=_detail_sort_key)`, and the sorted list is passed to all five builder functions. No re-sorting occurs.

### Chart Deduplication

Income trend deduplicates consecutive identical points:

```python
if last_x == rpt_dt and last_y == parsed:
    continue
```

Bank trend only emits on changes:

```python
if last_bank_type == bank_type:
    continue
```

This reduces response size and frontend rendering load without losing information.

### CSV Streaming with yield_per

```python
for main_row, identity_row in query.order_by(MainData.customer_id).yield_per(1000):
```

`yield_per(1000)` tells SQLAlchemy to fetch results in batches of 1000 from the database cursor, rather than loading the entire result set into memory. Combined with Python's generator pattern and `StreamingResponse`, this enables exporting millions of rows with constant memory usage.

### StringIO Buffer Reuse

```python
buffer = io.StringIO()
writer = csv.DictWriter(buffer, fieldnames=fieldnames)

for main_row, identity_row in ...:
    writer.writerow(row)
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
```

The same `StringIO` buffer is reused for every CSV row, avoiding the allocation and GC overhead of creating a new buffer per row.

---

## Configuration Caching

```python
@lru_cache
def get_settings() -> Settings:
    return Settings()
```

The `Settings` object is created exactly once and cached for the process lifetime. Environment variables are read at startup, and subsequent calls return the cached instance with no I/O.

---

## What Is NOT Optimized (Honest Assessment)

1. **No application-level caching**: There is no Redis, in-memory cache, or memoization for frequently accessed data (e.g., dashboard aggregates, customer summaries). Every request hits the database
2. **No query result caching**: The dashboard queries run fresh on every request. For high-traffic dashboards, caching the result for 30-60 seconds would significantly reduce DB load
3. **Synchronous ORM**: SQLAlchemy sessions are synchronous. While this works fine for CPU-bound analytics, it means each request blocks a worker thread during DB I/O
4. **Identity map in memory**: The upload identity map loads the entire identity file into a Python dict. For very large identity files (millions of rows), this could become a memory bottleneck
5. **No connection pooling tuning**: The default SQLAlchemy pool settings are used — no explicit `pool_size`, `max_overflow`, or `pool_timeout` configuration
6. **No query plan optimization**: While indexes exist, there are no explicit `EXPLAIN ANALYZE` validations or query hints documented
