"""Service layer for CIBIL data file uploads.

This module is responsible for:
* Reading uploaded pipe-separated TXT files as streams.
* Building an in-memory identity lookup keyed by CUSTOMER_ID.
* Iterating over the main file row by row and joining identity data.
* Persisting joined records into the database with SQLAlchemy.
* Skipping bad rows while keeping counters for reporting.
* Supporting background processing with real-time progress tracking.

Upload flow (async):
  1. POST /upload/files  → saves files to temp, creates UploadHistory(status=processing),
     returns upload_id immediately.
  2. BackgroundTasks worker calls process_upload_background() which reads from temp
     files, inserts in batches, and updates progress_current/progress_total every
     PROGRESS_UPDATE_INTERVAL rows.
  3. Frontend polls GET /upload/status/{upload_id} to show a progress bar.
  4. Temp files are cleaned up after processing finishes (success or failure).
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
import json
import logging
import tempfile
import shutil
from pathlib import Path
from typing import BinaryIO

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.identity_data_model import IdentityData
from app.models.main_data_model import MainData
from app.models.upload_error_model import UploadError
from app.models.upload_history_model import UploadHistory, UploadStatus


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Batch size for high-volume bulk inserts.  Tuned to balance memory usage
# against the overhead of many small INSERT statements.
BATCH_SIZE = 10_000

# Maximum length of raw_data stored in the upload_errors table.
RAW_DATA_MAX_CHARS = 1000

# How often (in rows) to persist progress_current to the DB so the polling
# endpoint can report meaningful progress.
PROGRESS_UPDATE_INTERVAL = 5_000


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_raw_data(value: object) -> str:
    """Serialize *value* to JSON then truncate to a safe max length.

    Used when logging failed rows into upload_errors — we want a best-effort
    representation of the offending data without blowing up the column.
    """
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
    """Yield decoded text lines from a file on disk.

    Used by the background processor which reads from temp files rather
    than from in-memory UploadFile objects.
    """
    with open(path, "rb") as f:
        for raw_line in f:
            yield raw_line.decode("utf-8", errors="replace")


def _iter_decoded_lines(file: UploadFile) -> Iterable[str]:
    """Yield decoded text lines from an UploadFile without loading it fully.

    UploadFile.file is a SpooledTemporaryFile (binary). Wrapping it in an
    iterator that decodes per-chunk avoids reading the full file into memory.
    """

    def _line_iterator(binary: BinaryIO) -> Iterable[bytes]:
        while True:
            line = binary.readline()
            if not line:
                break
            yield line

    for raw_line in _line_iterator(file.file):
        # Decode each line individually; errors are replaced to avoid crashes
        # on bad bytes.
        yield raw_line.decode("utf-8", errors="replace")


def _build_identity_map_from_path(path: Path) -> dict[str, dict[str, str]]:
    """Build a CUSTOMER_ID → identity-row dict from a pipe-separated file on disk.

    NOTE: Keeps the full identity file in memory, which is acceptable for
    the current dataset size.  Revisit if identity files grow to millions.
    """
    reader = csv.DictReader(_iter_decoded_lines_from_path(path), delimiter="|")
    identity_map: dict[str, dict[str, str]] = {}
    for row in reader:
        customer_id = (row.get("CUSTOMER_ID") or "").strip()
        if not customer_id:
            continue
        identity_map[customer_id] = row
    return identity_map


def _build_identity_map(identity_file: UploadFile) -> dict[str, dict[str, str]]:
    """Build a CUSTOMER_ID → identity-row dict from an UploadFile object.

    Used by the synchronous upload path.
    """
    reader = csv.DictReader(_iter_decoded_lines(identity_file), delimiter="|")
    identity_map: dict[str, dict[str, str]] = {}
    for row in reader:
        customer_id = (row.get("CUSTOMER_ID") or "").strip()
        if not customer_id:
            continue
        identity_map[customer_id] = row
    return identity_map


def _normalize_empty(value: str | None) -> str | None:
    """Convert empty-string-like values (including '\"\"') to None.

    Ensures consistent NULL representation in the database for blank fields.
    """
    if value is None:
        return None
    value = value.strip()
    if not value or value == '""':
        return None
    return value


def _count_data_rows(path: Path) -> int:
    """Count data rows in a pipe-separated file (excluding the header line).

    This gives us the progress_total denominator before processing starts.
    """
    count = 0
    with open(path, "rb") as f:
        for _ in f:
            count += 1
    # First line is the header row — subtract it.
    return max(count - 1, 0)


def _save_upload_to_temp(file: UploadFile) -> Path:
    """Persist an UploadFile to a temporary file and return its path.

    Background processing happens outside the request lifecycle, so we need
    the file contents on disk rather than in a SpooledTemporaryFile that gets
    closed when the request ends.
    """
    suffix = Path(file.filename or "upload.txt").suffix
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        shutil.copyfileobj(file.file, tmp)
    finally:
        tmp.close()
    return Path(tmp.name)


# ---------------------------------------------------------------------------
# Async (background) upload flow
# ---------------------------------------------------------------------------

def create_upload_record(
    db: Session,
    *,
    main_file: UploadFile,
    identity_file: UploadFile,
    uploaded_by_user_id: int | None,
) -> tuple[int, Path, Path]:
    """Create an UploadHistory row with status=processing and save files to temp.

    This runs inside the request handler so the caller can return the
    upload_id immediately. The actual parsing happens in the background.

    Returns (upload_id, main_temp_path, identity_temp_path).
    """
    # Persist uploaded files to temp so the background thread can access them.
    main_path = _save_upload_to_temp(main_file)
    identity_path = _save_upload_to_temp(identity_file)

    history = UploadHistory(
        main_filename=main_file.filename or "main.txt",
        identity_filename=identity_file.filename or "identity.txt",
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

    return history.id, main_path, identity_path


def process_upload_background(
    upload_id: int,
    main_path: Path,
    identity_path: Path,
) -> None:
    """Entry point for the BackgroundTasks worker.

    Creates its own DB session because the request-scoped session is already
    closed by the time this runs.  Cleans up temp files when done.
    """
    db = SessionLocal()
    try:
        _process_files(db, upload_id, main_path, identity_path)
    except Exception:
        logger.exception("Background upload processing failed for upload_id=%s", upload_id)
        # Best-effort: mark the upload as failed so the polling endpoint
        # doesn't stay stuck on "processing" forever.
        try:
            history = db.get(UploadHistory, upload_id)
            if history:
                history.status = UploadStatus.FAILED
                db.commit()
        except Exception:
            logger.exception("Failed to mark upload_id=%s as failed", upload_id)
    finally:
        db.close()
        # Clean up temporary files regardless of success/failure.
        for p in (main_path, identity_path):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass


def _process_files(
    db: Session,
    upload_id: int,
    main_path: Path,
    identity_path: Path,
) -> None:
    """Core background processing: count rows, parse, join, insert, track progress."""
    snapshot_id = upload_id

    # --- Step 1: Count total rows so the frontend can show a real progress bar ---
    total_rows = _count_data_rows(main_path)
    history = db.get(UploadHistory, upload_id)
    if not history:
        logger.error("UploadHistory %s not found, aborting background processing", upload_id)
        return
    history.progress_total = total_rows
    db.commit()

    # --- Step 2: Build identity lookup from the identity file ---
    identity_map = _build_identity_map_from_path(identity_path)

    # --- Step 3: Stream main file and process in batches ---
    reader = csv.DictReader(_iter_decoded_lines_from_path(main_path), delimiter="|")

    records_inserted = 0
    records_failed = 0
    rows_processed = 0

    # In-memory buffers for high-throughput bulk inserts.
    main_batch: list[dict[str, object]] = []
    identity_batch: list[dict[str, object]] = []
    main_batch_row_numbers: list[int] = []
    error_batch: list[dict[str, object]] = []

    def flush_batches() -> None:
        """Bulk-insert accumulated rows and clear buffers.

        Uses a SAVEPOINT (begin_nested) so a single bad batch doesn't
        roll back the entire upload — we log the errors and keep going.
        """
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
                # Only count rows as inserted after a successful flush.
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
                "Bulk insert failed for batch of %d main rows. "
                "Marked rows as failed and continuing ingestion.",
                failed_rows,
            )

            # Try to persist the error records separately.
            if error_batch:
                try:
                    with db.begin_nested():
                        db.bulk_insert_mappings(UploadError, error_batch)
                        db.flush()
                except Exception:
                    logger.exception(
                        "Failed to persist upload error rows for snapshot_id=%s", snapshot_id
                    )
        finally:
            main_batch.clear()
            identity_batch.clear()
            main_batch_row_numbers.clear()
            error_batch.clear()

    def update_progress() -> None:
        """Write current counters to the DB so the polling endpoint can read them."""
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

    # --- Step 4: Iterate rows, buffer data, and insert in batches ---
    for row_number, row in enumerate(reader, start=2):
        try:
            customer_id = (row.get("CUSTOMER_ID") or "").strip()
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
                    "snapshot_id": snapshot_id,
                }
            )
            main_batch_row_numbers.append(row_number)

            # Only create identity_data row if we have a matching identity record.
            if identity_row:
                identity_batch.append(
                    {
                        "customer_id": _normalize_empty(customer_id),
                        "pan": _normalize_empty(identity_row.get("PAN")),
                        "passport": _normalize_empty(identity_row.get("PASSPORT")),
                        "voter_id": _normalize_empty(identity_row.get("VOTER_ID")),
                        "uid": _normalize_empty(identity_row.get("UID")),
                        "ration_card": _normalize_empty(identity_row.get("RATION_CARD")),
                        "driving_license": _normalize_empty(
                            identity_row.get("DRIVING_LICENSE")
                        ),
                        "snapshot_id": snapshot_id,
                    }
                )

            # Flush when batch threshold is reached.
            if len(main_batch) >= BATCH_SIZE:
                flush_batches()
        except Exception as e:
            # Skip and log rows that cannot be processed at all.
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

    # Flush any remaining buffered data after finishing the file.
    flush_batches()

    # --- Step 5: Determine final status and persist ---
    status = UploadStatus.SUCCESS
    if not records_inserted and not records_failed:
        # Empty file — no header-only or completely blank.
        status = UploadStatus.FAILED
    elif records_failed and records_inserted:
        status = UploadStatus.PARTIAL
    elif records_failed and not records_inserted:
        status = UploadStatus.FAILED

    history.records_inserted = records_inserted
    history.records_failed = records_failed
    history.progress_current = rows_processed
    history.status = status
    db.commit()


# ---------------------------------------------------------------------------
# Synchronous upload (original API — kept for backward compatibility)
# ---------------------------------------------------------------------------

def process_upload_files(
    db: Session,
    *,
    main_file: UploadFile,
    identity_file: UploadFile,
    uploaded_by_user_id: int | None,
) -> dict[str, int | str]:
    """Parse, join, and persist data from the uploaded CIBIL files (synchronous).

    This is the original blocking implementation.  The POST /upload/files
    endpoint now uses the async flow, but this function is retained so that
    existing tests and any direct callers continue to work.
    """
    # Create the upload history record up-front so we get a snapshot_id.
    history = UploadHistory(
        main_filename=main_file.filename or "main.txt",
        identity_filename=identity_file.filename or "identity.txt",
        records_inserted=0,
        records_failed=0,
        uploaded_by=uploaded_by_user_id,
        status=UploadStatus.SUCCESS,
    )
    db.add(history)
    db.commit()  # Persist to get primary key value.
    db.refresh(history)

    snapshot_id = history.id

    # Build identity lookup from identity file.
    identity_map = _build_identity_map(identity_file)

    # Reset file pointer of main file to ensure we read from the beginning.
    main_file.file.seek(0)

    reader = csv.DictReader(_iter_decoded_lines(main_file), delimiter="|")

    records_inserted = 0
    records_failed = 0

    # In-memory buffers for high-throughput bulk inserts.
    main_batch: list[dict[str, object]] = []
    identity_batch: list[dict[str, object]] = []
    main_batch_row_numbers: list[int] = []
    error_batch: list[dict[str, object]] = []

    def flush_batches() -> None:
        """Bulk-insert accumulated rows and clear buffers safely.

        Using bulk_insert_mappings avoids per-row ORM overhead and is much
        faster for very large files, while still honoring snapshot_id and
        identity join logic.  We only flush here; a single commit happens
        after the entire file has been processed to keep transaction overhead low.
        """
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
                # Only count rows as inserted after a successful flush.
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
                "Bulk insert failed for batch of %d main rows (and matching identity rows). "
                "Marked rows as failed and continuing ingestion.",
                failed_rows,
            )

            if error_batch:
                try:
                    with db.begin_nested():
                        db.bulk_insert_mappings(UploadError, error_batch)
                        db.flush()
                except Exception:
                    logger.exception(
                        "Failed to persist upload error rows for snapshot_id=%s", snapshot_id
                    )
        finally:
            main_batch.clear()
            identity_batch.clear()
            main_batch_row_numbers.clear()
            error_batch.clear()

    # Iterate main rows, buffer data, and insert in batches.
    for row_number, row in enumerate(reader, start=2):
        try:
            customer_id = (row.get("CUSTOMER_ID") or "").strip()
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
                continue

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
                        "driving_license": _normalize_empty(
                            identity_row.get("DRIVING_LICENSE")
                        ),
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
            continue

    # Flush any remaining data after finishing the file.
    flush_batches()

    # Determine final status based on inserted/failed counts.
    status = UploadStatus.SUCCESS
    if not records_inserted and not records_failed:
        status = UploadStatus.FAILED
    elif records_failed and records_inserted:
        status = UploadStatus.PARTIAL
    elif records_failed and not records_inserted:
        status = UploadStatus.FAILED

    # Finalize the upload history record with aggregate statistics.
    history.records_inserted = records_inserted
    history.records_failed = records_failed
    history.status = status
    db.add(history)
    # Single commit for all batched inserts + history update.
    db.commit()

    return {
        "message": "Upload completed",
        "records_inserted": records_inserted,
        "records_failed": records_failed,
        "status": status,
    }
