"""Admin-only router for CIBIL file uploads with background processing.

Upload flow:
  1. POST /upload/files → validates files, saves to temp, creates a
     "processing" UploadHistory record, kicks off a BackgroundTasks worker,
     and returns the upload_id immediately.
  2. GET /upload/status/{upload_id} → returns current progress and status
     so the frontend can render a progress bar and success/failure notification.
"""

from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.role_checker import admin_only, get_current_user
from app.models.upload_history_model import UploadHistory
from app.models.user_model import User
from app.schemas.upload_schema import (
    UploadAcceptedResponse,
    UploadStatusResponse,
)
from app.services.upload_service import (
    create_upload_record,
    process_upload_background,
)

router = APIRouter(prefix="/upload", tags=["Upload"])


def _validate_txt_file(file: UploadFile, field_name: str) -> None:
    """Ensure uploaded file has `.txt` extension as expected by the parser."""
    filename = file.filename or ""
    if not filename.lower().endswith(".txt"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} must be a .txt file",
        )


@router.post(
    "/files",
    response_model=UploadAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload CIBIL main and identity files (async)",
    responses={
        202: {
            "description": "Upload accepted — processing in background",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Upload accepted for processing",
                        "upload_id": 42,
                    }
                }
            },
        },
        400: {"description": "Invalid input files"},
        403: {"description": "Insufficient permissions"},
        422: {"description": "Validation error"},
    },
)
async def upload_files(
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(admin_only)],
    main_file: UploadFile = File(
        ..., description="Main CIBIL data file (pipe-separated .txt)"
    ),
    identity_file: UploadFile = File(
        ..., description="Identity CIBIL data file (pipe-separated .txt)"
    ),
) -> UploadAcceptedResponse:
    """Accept main + identity CIBIL files and start processing in background.

    Returns immediately with an upload_id that can be polled via
    GET /upload/status/{upload_id} to track progress.
    """
    _validate_txt_file(main_file, "main_file")
    _validate_txt_file(identity_file, "identity_file")

    # Save files to temp and create a "processing" history record.
    upload_id, main_path, identity_path = create_upload_record(
        db,
        main_file=main_file,
        identity_file=identity_file,
        uploaded_by_user_id=current_user.id,
    )

    # Schedule the heavy processing to run after the response is sent.
    background_tasks.add_task(
        process_upload_background,
        upload_id,
        main_path,
        identity_path,
    )

    return UploadAcceptedResponse(
        message="Upload accepted for processing",
        upload_id=upload_id,
    )


@router.get(
    "/status/{upload_id}",
    response_model=UploadStatusResponse,
    summary="Poll upload processing progress",
    responses={
        200: {
            "description": "Current upload progress and status",
            "content": {
                "application/json": {
                    "example": {
                        "upload_id": 42,
                        "status": "processing",
                        "progress_current": 25000,
                        "progress_total": 540234,
                        "records_inserted": 24800,
                        "records_failed": 200,
                    }
                }
            },
        },
        404: {"description": "Upload not found"},
    },
)
def get_upload_status(
    upload_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> UploadStatusResponse:
    """Return the current progress and status of an upload.

    The frontend should poll this endpoint (e.g. every 2-3 seconds) while
    status is "processing" to update the progress bar.  Once status changes
    to "success", "partial", or "failed", processing is complete.
    """
    history = db.get(UploadHistory, upload_id)
    if not history:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload {upload_id} not found",
        )

    return UploadStatusResponse(
        upload_id=history.id,
        status=history.status,
        progress_current=history.progress_current,
        progress_total=history.progress_total,
        records_inserted=history.records_inserted,
        records_failed=history.records_failed,
    )
