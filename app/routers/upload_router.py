"""Admin-only router for CIBIL file uploads."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.role_checker import admin_only
from app.models.user_model import User
from app.schemas.upload_schema import UploadResponse
from app.services.upload_service import process_upload_files

router = APIRouter(prefix="/upload", tags=["Upload"])


def _validate_txt_file(file: UploadFile, field_name: str) -> None:
    """Ensure uploaded file has `.txt` extension as expected."""
    filename = file.filename or ""
    if not filename.lower().endswith(".txt"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} must be a .txt file",
        )


@router.post(
    "/files",
    response_model=UploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload CIBIL main and identity files",
    responses={
        200: {
            "description": "Upload processed successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Upload completed",
                        "records_inserted": 540234,
                        "records_failed": 120,
                        "status": "partial",
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
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(admin_only)],
    main_file: UploadFile = File(..., description="Main CIBIL data file (pipe-separated .txt)"),
    identity_file: UploadFile = File(
        ..., description="Identity CIBIL data file (pipe-separated .txt)"
    ),
) -> UploadResponse:
    """Upload and process main + identity CIBIL files (admin-only)."""
    _validate_txt_file(main_file, "main_file")
    _validate_txt_file(identity_file, "identity_file")

    result = process_upload_files(
        db,
        main_file=main_file,
        identity_file=identity_file,
        uploaded_by_user_id=current_user.id,
    )

    return UploadResponse(**result)

