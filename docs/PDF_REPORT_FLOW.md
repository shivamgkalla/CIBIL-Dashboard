# PDF Report Flow

## Overview

The PDF report system generates bureau-style customer credit reports as downloadable PDF documents. It uses **ReportLab** (specifically the `platypus` high-level API) to create structured, multi-section reports with tables and key-value layouts.

---

## End-to-End Flow

```
GET /customers/{customer_id}/report/pdf
        │
        ▼
customer_router.py:download_customer_report_pdf()
  ├── Calls customer_service.get_customer_report_data(db, customer_id)
  ├── Checks if accounts exist → 404 if empty
  ├── Calls pdf_service.generate_customer_pdf(report_data)
  └── Returns StreamingResponse (application/pdf)
```

---

## Step 1: Data Preparation (`get_customer_report_data`)

**File**: `app/services/customer_service.py`

This function converts internal data structures into a flat dict optimized for PDF rendering.

### Data Gathering

1. Calls `get_customer_details(db, customer_id)` — returns all main + identity records across all snapshots (identity already masked)
2. Calls `get_customer_timeline(db, customer_id)` — returns chronological timeline (identity already masked)

### Output Structure

```python
{
    "overview": {
        "customer_id": "CUST123",
        "primary_acct_key": "ACCT001",
        "bank_type": "PSU",
        "income": "75000",
        "rpt_dt": "2025-01-31",
    },
    "accounts": [
        {
            "acct_key": "ACCT001",
            "bank_type": "PSU",
            "income": "75000",
            "income_freq": "1",
            "occup_status_cd": "SAL",
            "rpt_dt": "2025-01-31",
            "snapshot_id": 5,
        },
        # ... one entry per main_data record
    ],
    "identity": {
        "pan": "ABCDE****F",
        "uid": "********9012",
        "passport": null,
        # ... (masked values from latest non-null identity)
    },
    "timeline": [
        {
            "snapshot_id": 1,
            "uploaded_at": datetime(...),
            "rpt_dt": "2024-06-30",
            "income": "50000",
            "bank_type": "PSU",
            "occup_status_cd": "SAL",
            "pan": "ABCDE****F",
            # ... (all timeline fields including masked identity)
        },
    ],
}
```

### Key Decisions

- **Overview** uses the latest record (determined by `max(details, key=_detail_sort_key)`)
- **Identity** uses `_get_latest_non_null_identity()` — walks backwards through snapshots to find the first identity with at least one populated field
- **Accounts** includes ALL records across ALL snapshots (not just the latest)
- **Timeline** is already ordered by the timeline service
- Identity values are already masked at this point (masking happened in `get_customer_details()` and `get_customer_timeline()`)
- If no details exist, returns an empty structure with just the customer_id in overview

---

## Step 2: PDF Generation (`generate_customer_pdf`)

**File**: `app/services/pdf_service.py`

### Document Setup

```python
doc = SimpleDocTemplate(
    buffer,
    pagesize=A4,
    topMargin=20 * mm,
    bottomMargin=20 * mm,
    leftMargin=15 * mm,
    rightMargin=15 * mm,
)
```

- **Page size**: A4 (210 × 297 mm)
- **Margins**: 20mm top/bottom, 15mm left/right
- **Output**: Written to a `BytesIO` buffer, returned as `bytes`

### Report Sections

The PDF is built as a `story` list of ReportLab flowable objects:

#### 1. Report Header

```
CREDIT INFORMATION REPORT
```

Centered, Helvetica-Bold 18pt, with 6mm spacer below.

#### 2. Customer Overview

A **key-value table** showing:
- Customer ID
- Primary Account Key
- Latest Bank Type
- Latest Income
- Latest Report Date

Uses `_build_key_value_table()` — a two-column table with bold labels on the left and values on the right. Empty/null values are automatically skipped.

#### 3. Account Information

A **data table** with 7 columns:

| Acct Key | Bank Type | Income | Income Freq | Occup Status | Report Date | Snapshot ID |

Design:
- Header row: `#EAEAEA` background, Helvetica-Bold
- Data rows: Alternating white / `#F7F7F7` backgrounds
- Font size: 7pt (compact to fit many columns)
- Column width: `page_width / 7` (equal distribution)
- `repeatRows=1` — header repeats on page breaks

If no accounts exist, shows a key-value entry: `"Status: No account records available."`

#### 4. Identity Information

A **key-value table** showing:
- PAN
- UID
- Passport
- Voter ID
- Driving License
- Ration Card

All values are already masked. Empty/null fields are automatically omitted by `_build_key_value_table()`.

#### 5. Timeline (conditional)

Only rendered if timeline data exists. A **data table** with 4 columns:

| Snapshot ID | Report Date | Income | Bank Type |

Same styling as the accounts table.

### Helper Functions

#### `_build_key_value_table(data, label_width, value_width)`

Creates a two-column table for label-value pairs:
- Filters out `None` and empty string values
- Labels: Helvetica-Bold 8pt
- Values: Helvetica 8pt
- If all values are empty, shows a single row with dashes

#### `_build_section_title(text)`

Creates a section heading: Helvetica-Bold 12pt with 10pt space before and 6pt after.

### Styling Constants

```python
_HEADER_BG = colors.HexColor("#EAEAEA")     # Table header background
_ALT_ROW_BG = colors.HexColor("#F7F7F7")    # Alternating row background
```

---

## Step 3: Response Delivery

The router wraps the raw PDF bytes in a `StreamingResponse`:

```python
pdf_bytes = generate_customer_pdf(report_data)
filename = f"customer_{customer_id}_report.pdf"
return StreamingResponse(
    io.BytesIO(pdf_bytes),
    media_type="application/pdf",
    headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
    },
)
```

The filename includes the customer_id for easy identification.

---

## Error Handling

The router checks for empty data before generating the PDF:

```python
if not report_data.get("accounts"):
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"No records found for customer_id={customer_id}",
    )
```

This prevents generating an empty PDF and keeps behavior consistent with other customer endpoints that return 404 for missing customers.

---

## Data Sensitivity

All identity fields in the PDF are **pre-masked** before reaching `pdf_service.py`. The PDF service receives already-masked data from `get_customer_report_data()`, which in turn gets masked data from `get_customer_details()` and `get_customer_timeline()`. This means:

- `pdf_service.py` has no knowledge of masking
- It renders whatever data it receives
- The masking guarantee is enforced upstream in `customer_service.py`

This separation of concerns means the PDF service can be tested and modified independently without risk of accidentally leaking raw identity data.

---

## Limitations and Trade-offs

1. **No page numbers**: The current implementation does not add page numbers or footers. For large account histories, this could make multi-page PDFs harder to navigate
2. **Fixed column widths**: Tables use equal column distribution (`width / N`), which may not be optimal when some columns have consistently short or long values
3. **No charts in PDF**: Unlike the JSON API which provides chart-ready data, the PDF only contains tabular data. Income trends and bank changes are not visualized
4. **Memory**: The entire PDF is built in memory (`BytesIO`) before being returned. For extremely large reports, this could be significant, though for typical customer data volumes it is acceptable
5. **No watermarking or branding**: The report uses a simple text header without company logos or confidentiality watermarks
