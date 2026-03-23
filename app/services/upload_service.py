"""Service layer for CIBIL data file uploads with auto-detection.

This module is responsible for:
* Accepting N pipe-separated TXT files.
* Auto-detecting each file's type by reading its header row.
* Building in-memory lookups for customer-level files.
* Streaming the account (main) file row by row, enriching with lookups.
* Inserting identity and inquiry data into their respective tables.
* Persisting joined records into the database with SQLAlchemy.
* Skipping bad rows while keeping counters for reporting.
* Supporting background processing with real-time progress tracking.

File classification by header columns:
  - ACCT_KEY             → account (main_data driver)
  - Score_V3 / CUST_ID   → credit_score (customer-level lookup)
  - INQ_PURP_CD          → inquiry (inquiry_data)
  - PAN / PASSPORT        → identity_docs (identity_data)
  - PHONE                 → phone (identity_data)
  - FULL_NAME / DOB       → personal (identity_data)
  - EMAIL                 → email (identity_data)
  - ADDRESS / PINCODE     → address (identity_data)
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
import json
import logging
import tempfile
import shutil
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.identity_data_model import IdentityData
from app.models.inquiry_data_model import InquiryData
from app.models.main_data_model import MainData
from app.models.upload_error_model import UploadError
from app.models.upload_history_model import UploadHistory, UploadStatus


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BATCH_SIZE = 10_000
RAW_DATA_MAX_CHARS = 1000
PROGRESS_UPDATE_INTERVAL = 5_000

# File type constants
FILE_TYPE_ACCOUNT = "account"
FILE_TYPE_CREDIT_SCORE = "credit_score"
FILE_TYPE_INQUIRY = "inquiry"
FILE_TYPE_IDENTITY_DOCS = "identity_docs"
FILE_TYPE_PHONE = "phone"
FILE_TYPE_PERSONAL = "personal"
FILE_TYPE_EMAIL = "email"
FILE_TYPE_ADDRESS = "address"
FILE_TYPE_UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------

def _read_header(path: Path) -> list[str]:
    """Read the first line of a file and return normalized column names."""
    with open(path, "rb") as f:
        first_line = f.readline().decode("utf-8", errors="replace").strip()
    return [col.strip().upper() for col in first_line.split("|")]


def classify_file(path: Path) -> str:
    """Determine the file type by inspecting its header columns."""
    headers = set(_read_header(path))

    if "ACCT_KEY" in headers:
        return FILE_TYPE_ACCOUNT
    if "SCORE_V3" in headers or ("CUST_ID" in headers and len(headers) <= 3):
        return FILE_TYPE_CREDIT_SCORE
    if "INQ_PURP_CD" in headers:
        return FILE_TYPE_INQUIRY
    if "PAN" in headers or "PASSPORT" in headers or "VOTER_ID" in headers:
        return FILE_TYPE_IDENTITY_DOCS
    if "FULL_NAME" in headers or ("DOB" in headers and "GENDER" in headers):
        return FILE_TYPE_PERSONAL
    if "PHONE" in headers and "EMAIL" not in headers:
        return FILE_TYPE_PHONE
    if "EMAIL" in headers and "PHONE" not in headers:
        return FILE_TYPE_EMAIL
    if "ADDRESS" in headers or "PINCODE" in headers:
        return FILE_TYPE_ADDRESS

    return FILE_TYPE_UNKNOWN


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_raw_data(value: object) -> str:
    """Serialize value to JSON then truncate to a safe max length."""
    try:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        try:
            serialized = repr(value)
        except Exception:
            serialized = "<unserializable>"
    try:
        return serialized[:RAW_DATA_MAX_CHARS]
    except Exception:
        return ""


def _iter_decoded_lines_from_path(path: Path) -> Iterable[str]:
    """Yield decoded text lines from a file on disk."""
    with open(path, "rb") as f:
        for raw_line in f:
            yield raw_line.decode("utf-8", errors="replace")


def _normalize_empty(value: str | None) -> str | None:
    """Convert empty-string-like values (including '\"\"') to None."""
    if value is None:
        return None
    value = value.strip()
    if not value or value == '""':
        return None
    return value


def _get_customer_id(row: dict[str, str]) -> str:
    """Extract CUSTOMER_ID from a row, handling CUST_ID alias."""
    return (row.get("CUSTOMER_ID") or row.get("CUST_ID") or "").strip()


def _count_data_rows(path: Path) -> int:
    """Count data rows in a pipe-separated file (excluding header)."""
    count = 0
    with open(path, "rb") as f:
        for _ in f:
            count += 1
    return max(count - 1, 0)


def _save_upload_to_temp(file: UploadFile) -> Path:
    """Persist an UploadFile to a temporary file and return its path."""
    suffix = Path(file.filename or "upload.txt").suffix
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        shutil.copyfileobj(file.file, tmp)
    finally:
        tmp.close()
    return Path(tmp.name)


# ---------------------------------------------------------------------------
# Customer-level lookup builders
# ---------------------------------------------------------------------------

def _build_customer_lookup(path: Path) -> dict[str, dict[str, str]]:
    """Build a CUSTOMER_ID → row dict from any customer-level file."""
    reader = csv.DictReader(_iter_decoded_lines_from_path(path), delimiter="|")
    lookup: dict[str, dict[str, str]] = {}
    for row in reader:
        # Normalize headers to uppercase for consistent access
        normalized = {k.strip().upper(): v.strip() if v else "" for k, v in row.items()}
        customer_id = (normalized.get("CUSTOMER_ID") or normalized.get("CUST_ID") or "").strip()
        if not customer_id:
            continue
        # Merge into existing entry (later files enrich earlier ones)
        if customer_id in lookup:
            lookup[customer_id].update(normalized)
        else:
            lookup[customer_id] = normalized
    return lookup


def _merge_lookups(*lookups: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """Merge multiple customer-level lookups into one."""
    merged: dict[str, dict[str, str]] = {}
    for lookup in lookups:
        for cid, data in lookup.items():
            if cid in merged:
                merged[cid].update(data)
            else:
                merged[cid] = dict(data)
    return merged


# ---------------------------------------------------------------------------
# Async (background) upload flow
# ---------------------------------------------------------------------------

def create_upload_record(
    db: Session,
    *,
    files: list[UploadFile],
    uploaded_by_user_id: int | None,
) -> tuple[int, list[Path]]:
    """Create an UploadHistory row and save files to temp.

    Returns (upload_id, list_of_temp_paths).
    """
    temp_paths = [_save_upload_to_temp(f) for f in files]
    all_filenames = ", ".join(f.filename or "unknown.txt" for f in files)

    history = UploadHistory(
        main_filename=None,
        identity_filename=None,
        filenames=all_filenames,
        records_inserted=0,
        records_failed=0,
        uploaded_by=uploaded_by_user_id,
        status=UploadStatus.PROCESSING,
        progress_current=0,
        progress_total=0,
    )
    db.add(history)
    db.commit()
    db.refresh(history)

    return history.id, temp_paths


def process_upload_background(
    upload_id: int,
    temp_paths: list[Path],
) -> None:
    """Entry point for the BackgroundTasks worker."""
    db = SessionLocal()
    try:
        _process_files_multi(db, upload_id, temp_paths)
    except Exception:
        logger.exception("Background upload processing failed for upload_id=%s", upload_id)
        try:
            history = db.get(UploadHistory, upload_id)
            if history:
                history.status = UploadStatus.FAILED
                db.commit()
        except Exception:
            logger.exception("Failed to mark upload_id=%s as failed", upload_id)
    finally:
        db.close()
        for p in temp_paths:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass


def _process_files_multi(
    db: Session,
    upload_id: int,
    temp_paths: list[Path],
) -> None:
    """Core processing: classify files, build lookups, insert data."""
    snapshot_id = upload_id

    history = db.get(UploadHistory, upload_id)
    if not history:
        logger.error("UploadHistory %s not found, aborting", upload_id)
        return

    # --- Step 1: Classify all files ---
    classified: dict[str, list[Path]] = {}
    for path in temp_paths:
        file_type = classify_file(path)
        classified.setdefault(file_type, []).append(path)
        logger.info("Classified %s as %s", path.name, file_type)

    account_files = classified.get(FILE_TYPE_ACCOUNT, [])

    # --- Step 2: Count total rows for progress tracking ---
    # When account files are present, progress is driven by account rows
    # (the streaming loop). Otherwise, count all files.
    if account_files:
        total_rows = sum(_count_data_rows(p) for p in account_files)
    else:
        total_rows = sum(_count_data_rows(p) for p in temp_paths)
    history.progress_total = total_rows
    db.commit()

    # --- Step 3: Process non-account files ---
    records_inserted = 0

    # Inquiry files always insert directly (not part of account enrichment)
    for inq_path in classified.get(FILE_TYPE_INQUIRY, []):
        records_inserted += _insert_inquiry_data(db, inq_path, snapshot_id)

    if not account_files:
        # No account file — insert every other file type directly into
        # its own table.  When account files ARE present, credit_score /
        # personal / identity files are handled via the enrichment path
        # (Step 4-5) to avoid duplicate rows.

        # Credit score → sparse main_data rows (customer_id + credit_score)
        for cs_path in classified.get(FILE_TYPE_CREDIT_SCORE, []):
            records_inserted += _insert_credit_score_data(db, cs_path, snapshot_id)

        # Personal → sparse main_data rows (customer_id + name/dob/gender)
        for p_path in classified.get(FILE_TYPE_PERSONAL, []):
            records_inserted += _insert_personal_data(db, p_path, snapshot_id)

        # Identity-category files → identity_data
        identity_types = [
            FILE_TYPE_IDENTITY_DOCS, FILE_TYPE_PHONE, FILE_TYPE_EMAIL, FILE_TYPE_ADDRESS,
        ]
        for id_type in identity_types:
            for id_path in classified.get(id_type, []):
                records_inserted += _insert_identity_data_standalone(db, id_path, snapshot_id)

    # --- Step 4: If account files present, build lookups and stream ---
    if account_files:
        # Build customer-level lookups for enriching account rows
        identity_docs_lookup: dict[str, dict[str, str]] = {}
        credit_score_lookup: dict[str, dict[str, str]] = {}
        personal_lookup: dict[str, dict[str, str]] = {}
        phone_lookup: dict[str, dict[str, str]] = {}
        email_lookup: dict[str, dict[str, str]] = {}
        address_lookup: dict[str, dict[str, str]] = {}

        for file_type, paths in classified.items():
            for path in paths:
                if file_type == FILE_TYPE_IDENTITY_DOCS:
                    identity_docs_lookup = _merge_lookups(identity_docs_lookup, _build_customer_lookup(path))
                elif file_type == FILE_TYPE_CREDIT_SCORE:
                    credit_score_lookup = _merge_lookups(credit_score_lookup, _build_customer_lookup(path))
                elif file_type == FILE_TYPE_PERSONAL:
                    personal_lookup = _merge_lookups(personal_lookup, _build_customer_lookup(path))
                elif file_type == FILE_TYPE_PHONE:
                    phone_lookup = _merge_lookups(phone_lookup, _build_customer_lookup(path))
                elif file_type == FILE_TYPE_EMAIL:
                    email_lookup = _merge_lookups(email_lookup, _build_customer_lookup(path))
                elif file_type == FILE_TYPE_ADDRESS:
                    address_lookup = _merge_lookups(address_lookup, _build_customer_lookup(path))

        identity_map = _merge_lookups(
            identity_docs_lookup, personal_lookup, phone_lookup, email_lookup, address_lookup
        )

    # --- Step 5: Stream account file(s) and process in batches ---
    records_failed = 0
    rows_processed = 0

    if account_files:
        main_batch: list[dict[str, object]] = []
        identity_batch: list[dict[str, object]] = []
        main_batch_row_numbers: list[int] = []
        error_batch: list[dict[str, object]] = []

        def flush_batches() -> None:
            nonlocal records_failed, records_inserted

            if not main_batch and not identity_batch and not error_batch:
                return

            try:
                with db.begin_nested():
                    if main_batch:
                        db.bulk_insert_mappings(MainData, main_batch)
                    if identity_batch:
                        db.bulk_insert_mappings(IdentityData, identity_batch)
                    if error_batch:
                        db.bulk_insert_mappings(UploadError, error_batch)
                    db.flush()
                    records_inserted += len(main_batch)
            except Exception as e:
                failed_rows = len(main_batch)
                if failed_rows:
                    batch_error_message = f"{type(e).__name__}: {e}"
                    for row_number, raw in zip(main_batch_row_numbers, main_batch, strict=False):
                        error_batch.append(
                            {
                                "upload_id": snapshot_id,
                                "row_number": row_number,
                                "error_message": batch_error_message,
                                "raw_data": _safe_raw_data(raw),
                            }
                        )
                logger.exception(
                    "Bulk insert failed for batch of %d main rows.",
                    failed_rows,
                )
                if error_batch:
                    try:
                        with db.begin_nested():
                            db.bulk_insert_mappings(UploadError, error_batch)
                            db.flush()
                    except Exception:
                        logger.exception(
                            "Failed to persist error rows for snapshot_id=%s", snapshot_id
                        )
            finally:
                main_batch.clear()
                identity_batch.clear()
                main_batch_row_numbers.clear()
                error_batch.clear()

        def update_progress() -> None:
            try:
                history.progress_current = rows_processed
                history.records_inserted = records_inserted
                history.records_failed = records_failed
                db.commit()
                db.refresh(history)
            except Exception:
                logger.warning(
                    "Failed to update progress for upload_id=%s", upload_id, exc_info=True
                )

        for account_path in account_files:
            reader = csv.DictReader(_iter_decoded_lines_from_path(account_path), delimiter="|")

            for row_number, row in enumerate(reader, start=2):
                try:
                    customer_id = _get_customer_id(row)
                    if not customer_id:
                        records_failed += 1
                        error_batch.append(
                            {
                                "upload_id": snapshot_id,
                                "row_number": row_number,
                                "error_message": "Missing CUSTOMER_ID",
                                "raw_data": _safe_raw_data(row),
                            }
                        )
                        if len(error_batch) >= BATCH_SIZE:
                            flush_batches()
                        rows_processed += 1
                        if rows_processed % PROGRESS_UPDATE_INTERVAL == 0:
                            update_progress()
                        continue

                    # Enrich from customer-level lookups
                    score_row = credit_score_lookup.get(customer_id, {})
                    personal_row = personal_lookup.get(customer_id, {})
                    identity_row = identity_map.get(customer_id)

                    main_batch.append(
                        {
                            "acct_key": _normalize_empty(row.get("ACCT_KEY")),
                            "customer_id": _normalize_empty(customer_id),
                            "income": _normalize_empty(row.get("INCOME")),
                            "income_freq": _normalize_empty(row.get("INCOME_FREQ")),
                            "occup_status_cd": _normalize_empty(row.get("OCCUP_STATUS_CD")),
                            "rpt_dt": _normalize_empty(row.get("RPT_DT")),
                            "bank_type": _normalize_empty(row.get("BANK_TYPE")),
                            "credit_score": _normalize_empty(score_row.get("SCORE_V3")),
                            "full_name": _normalize_empty(personal_row.get("FULL_NAME")),
                            "dob": _normalize_empty(personal_row.get("DOB")),
                            "gender": _normalize_empty(personal_row.get("GENDER")),
                            "snapshot_id": snapshot_id,
                        }
                    )
                    main_batch_row_numbers.append(row_number)

                    if identity_row:
                        identity_batch.append(
                            {
                                "customer_id": _normalize_empty(customer_id),
                                "pan": _normalize_empty(identity_row.get("PAN")),
                                "passport": _normalize_empty(identity_row.get("PASSPORT")),
                                "voter_id": _normalize_empty(identity_row.get("VOTER_ID")),
                                "uid": _normalize_empty(identity_row.get("UID")),
                                "ration_card": _normalize_empty(identity_row.get("RATION_CARD")),
                                "driving_license": _normalize_empty(identity_row.get("DRIVING_LICENSE")),
                                "phone": _normalize_empty(identity_row.get("PHONE")),
                                "email": _normalize_empty(identity_row.get("EMAIL")),
                                "address": _normalize_empty(identity_row.get("ADDRESS")),
                                "pincode": _normalize_empty(identity_row.get("PINCODE")),
                                "snapshot_id": snapshot_id,
                            }
                        )

                    if len(main_batch) >= BATCH_SIZE:
                        flush_batches()
                except Exception as e:
                    records_failed += 1
                    error_batch.append(
                        {
                            "upload_id": snapshot_id,
                            "row_number": row_number,
                            "error_message": f"{type(e).__name__}: {e}",
                            "raw_data": _safe_raw_data(row),
                        }
                    )
                    if len(error_batch) >= BATCH_SIZE:
                        flush_batches()

                rows_processed += 1
                if rows_processed % PROGRESS_UPDATE_INTERVAL == 0:
                    update_progress()

        # Flush remaining buffered data
        flush_batches()

    # --- Step 6: Determine final status ---
    status = UploadStatus.SUCCESS
    if not records_inserted and not records_failed:
        status = UploadStatus.FAILED
    elif records_failed and records_inserted:
        status = UploadStatus.PARTIAL
    elif records_failed and not records_inserted:
        status = UploadStatus.FAILED

    history.records_inserted = records_inserted
    history.records_failed = records_failed
    history.progress_current = rows_processed if account_files else total_rows
    history.status = status
    db.commit()


# ---------------------------------------------------------------------------
# Standalone file insertion (no account file required)
# ---------------------------------------------------------------------------

def _insert_credit_score_data(db: Session, path: Path, snapshot_id: int) -> int:
    """Read a credit-score file and insert sparse main_data rows."""
    reader = csv.DictReader(_iter_decoded_lines_from_path(path), delimiter="|")
    batch: list[dict[str, object]] = []
    inserted = 0

    for row in reader:
        normalized = {k.strip().upper(): v.strip() if v else "" for k, v in row.items()}
        customer_id = (normalized.get("CUSTOMER_ID") or normalized.get("CUST_ID") or "").strip()
        if not customer_id:
            continue

        batch.append(
            {
                "customer_id": _normalize_empty(customer_id),
                "credit_score": _normalize_empty(normalized.get("SCORE_V3")),
                "snapshot_id": snapshot_id,
            }
        )

        if len(batch) >= BATCH_SIZE:
            try:
                with db.begin_nested():
                    db.bulk_insert_mappings(MainData, batch)
                    db.flush()
                    inserted += len(batch)
            except Exception:
                logger.exception("Failed to insert credit_score batch for snapshot_id=%s", snapshot_id)
            batch.clear()

    if batch:
        try:
            with db.begin_nested():
                db.bulk_insert_mappings(MainData, batch)
                db.flush()
                inserted += len(batch)
        except Exception:
            logger.exception("Failed to insert final credit_score batch for snapshot_id=%s", snapshot_id)
        batch.clear()

    return inserted


def _insert_personal_data(db: Session, path: Path, snapshot_id: int) -> int:
    """Read a personal file and insert sparse main_data rows."""
    reader = csv.DictReader(_iter_decoded_lines_from_path(path), delimiter="|")
    batch: list[dict[str, object]] = []
    inserted = 0

    for row in reader:
        normalized = {k.strip().upper(): v.strip() if v else "" for k, v in row.items()}
        customer_id = (normalized.get("CUSTOMER_ID") or normalized.get("CUST_ID") or "").strip()
        if not customer_id:
            continue

        batch.append(
            {
                "customer_id": _normalize_empty(customer_id),
                "full_name": _normalize_empty(normalized.get("FULL_NAME")),
                "dob": _normalize_empty(normalized.get("DOB")),
                "gender": _normalize_empty(normalized.get("GENDER")),
                "snapshot_id": snapshot_id,
            }
        )

        if len(batch) >= BATCH_SIZE:
            try:
                with db.begin_nested():
                    db.bulk_insert_mappings(MainData, batch)
                    db.flush()
                    inserted += len(batch)
            except Exception:
                logger.exception("Failed to insert personal batch for snapshot_id=%s", snapshot_id)
            batch.clear()

    if batch:
        try:
            with db.begin_nested():
                db.bulk_insert_mappings(MainData, batch)
                db.flush()
                inserted += len(batch)
        except Exception:
            logger.exception("Failed to insert final personal batch for snapshot_id=%s", snapshot_id)
        batch.clear()

    return inserted


def _insert_identity_data_standalone(db: Session, path: Path, snapshot_id: int) -> int:
    """Read an identity-category file and insert into identity_data."""
    reader = csv.DictReader(_iter_decoded_lines_from_path(path), delimiter="|")
    batch: list[dict[str, object]] = []
    inserted = 0

    for row in reader:
        normalized = {k.strip().upper(): v.strip() if v else "" for k, v in row.items()}
        customer_id = (normalized.get("CUSTOMER_ID") or normalized.get("CUST_ID") or "").strip()
        if not customer_id:
            continue

        batch.append(
            {
                "customer_id": _normalize_empty(customer_id),
                "pan": _normalize_empty(normalized.get("PAN")),
                "passport": _normalize_empty(normalized.get("PASSPORT")),
                "voter_id": _normalize_empty(normalized.get("VOTER_ID")),
                "uid": _normalize_empty(normalized.get("UID")),
                "ration_card": _normalize_empty(normalized.get("RATION_CARD")),
                "driving_license": _normalize_empty(normalized.get("DRIVING_LICENSE")),
                "phone": _normalize_empty(normalized.get("PHONE")),
                "email": _normalize_empty(normalized.get("EMAIL")),
                "address": _normalize_empty(normalized.get("ADDRESS")),
                "pincode": _normalize_empty(normalized.get("PINCODE")),
                "snapshot_id": snapshot_id,
            }
        )

        if len(batch) >= BATCH_SIZE:
            try:
                with db.begin_nested():
                    db.bulk_insert_mappings(IdentityData, batch)
                    db.flush()
                    inserted += len(batch)
            except Exception:
                logger.exception("Failed to insert identity batch for snapshot_id=%s", snapshot_id)
            batch.clear()

    if batch:
        try:
            with db.begin_nested():
                db.bulk_insert_mappings(IdentityData, batch)
                db.flush()
                inserted += len(batch)
        except Exception:
            logger.exception("Failed to insert final identity batch for snapshot_id=%s", snapshot_id)
        batch.clear()

    return inserted


# ---------------------------------------------------------------------------
# Inquiry data insertion
# ---------------------------------------------------------------------------

def _insert_inquiry_data(db: Session, path: Path, snapshot_id: int) -> int:
    """Read an inquiry file and bulk-insert into inquiry_data."""
    reader = csv.DictReader(_iter_decoded_lines_from_path(path), delimiter="|")
    batch: list[dict[str, object]] = []
    inserted = 0

    for row in reader:
        customer_id = _get_customer_id(row)
        if not customer_id:
            continue

        batch.append(
            {
                "customer_id": _normalize_empty(customer_id),
                "inq_purp_cd": _normalize_empty(row.get("INQ_PURP_CD")),
                "inq_date": _normalize_empty(row.get("INQ_DATE")),
                "m_sub_id": _normalize_empty(row.get("M_SUB_ID")),
                "amount": _normalize_empty(row.get("AMOUNT")),
                "snapshot_id": snapshot_id,
            }
        )

        if len(batch) >= BATCH_SIZE:
            try:
                with db.begin_nested():
                    db.bulk_insert_mappings(InquiryData, batch)
                    db.flush()
                    inserted += len(batch)
            except Exception:
                logger.exception("Failed to insert inquiry batch for snapshot_id=%s", snapshot_id)
            batch.clear()

    if batch:
        try:
            with db.begin_nested():
                db.bulk_insert_mappings(InquiryData, batch)
                db.flush()
                inserted += len(batch)
        except Exception:
            logger.exception("Failed to insert final inquiry batch for snapshot_id=%s", snapshot_id)
        batch.clear()

    return inserted
