"""ORM model for persisting per-row upload parsing errors."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UploadError(Base):
    """Stores row-level errors encountered during an upload run."""

    __tablename__ = "upload_errors"
    __table_args__ = (
        Index("ix_upload_errors_upload_id", "upload_id"),
        Index("ix_upload_errors_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    upload_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("upload_history.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    raw_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

