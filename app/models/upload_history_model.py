"""ORM model for tracking CIBIL file upload runs."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UploadStatus(str):
    """Simple string-based status values for an upload run."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class UploadHistory(Base):
    """Audit log of each bulk upload, including success/failure counts."""

    __tablename__ = "upload_history"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    main_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    identity_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    records_inserted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(index=True, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), default=UploadStatus.SUCCESS, nullable=False)

