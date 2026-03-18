"""Service layer for CIBIL data file uploads.

This module is responsible for:
* Reading uploaded pipe-separated TXT files as streams.
* Building an in-memory identity lookup keyed by CUSTOMER_ID.
* Iterating over the main file row by row and joining identity data.
* Persisting joined records into the database with SQLAlchemy.
* Skipping bad rows while keeping counters for reporting.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
import json
import logging
from typing import BinaryIO

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models.identity_data_model import IdentityData
from app.models.main_data_model import MainData
from app.models.upload_error_model import UploadError
from app.models.upload_history_model import UploadHistory, UploadStatus


logger = logging.getLogger(__name__)


# Batch size for high-volume bulk inserts.
BATCH_SIZE = 10_000
RAW_DATA_MAX_CHARS = 1000


def _safe_raw_data(value: object) -> str:
    """Serialize to JSON then truncate to a safe maximum length."""
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
        # Decode each line individually; errors are replaced to avoid crashes on bad bytes.
        yield raw_line.decode("utf-8", errors="replace")


def _build_identity_map(identity_file: UploadFile) -> dict[str, dict[str, str]]:
    """Build a CUSTOMER_ID → identity-row map from the identity file.

    NOTE: This keeps the full identity file in memory, which is acceptable for
    the current expected dataset size. If identity files grow to millions of
    rows, this may need to be revisited in favor of a streaming or partitioned
    join strategy to further reduce memory pressure.
    """
    reader = csv.DictReader(_iter_decoded_lines(identity_file), delimiter="|")
    identity_map: dict[str, dict[str, str]] = {}
    for row in reader:
        customer_id = (row.get("CUSTOMER_ID") or "").strip()
        if not customer_id:
            # Skip rows that cannot be matched to any main record.
            continue
        identity_map[customer_id] = row
    return identity_map


def _normalize_empty(value: str | None) -> str | None:
    """Convert empty-string-like values (including '\"\"') to None."""
    if value is None:
        return None
    value = value.strip()
    if not value or value == '""':
        return None
    return value


def process_upload_files(
    db: Session,
    *,
    main_file: UploadFile,
    identity_file: UploadFile,
    uploaded_by_user_id: int | None,
) -> dict[str, int | str]:
    """Parse, join, and persist data from the uploaded CIBIL files.

    This function performs the high-level orchestration:
    * Build an in-memory identity map keyed by CUSTOMER_ID.
    * Stream the main file with DictReader and join identity rows.
    * Insert MainData and IdentityData rows.
    * Record an UploadHistory row with aggregate statistics.
    """
    # Step 1: create UploadHistory record at the start of the upload.
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

    # Step 2: snapshot_id is the UploadHistory primary key.
    snapshot_id = history.id

    # Step 3: build identity lookup from identity file.
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
        identity join logic. We only flush here; a single commit happens after
        the entire file has been processed to keep transaction overhead low.
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

    # Step 4 & 5: iterate main rows, buffer data, and insert in batches.
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

            # When batch threshold is reached, flush accumulated rows.
            if len(main_batch) >= BATCH_SIZE:
                flush_batches()
        except Exception as e:
            # Step 6 (partial): count and skip rows that cannot be processed.
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

    status = UploadStatus.SUCCESS
    if records_failed and records_inserted:
        status = UploadStatus.PARTIAL
    elif records_failed and not records_inserted:
        status = UploadStatus.FAILED

    # Step 6: update UploadHistory record with final counters and status.
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

