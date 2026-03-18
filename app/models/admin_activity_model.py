"""Admin action audit logging ORM model."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AdminActivity(Base):
    """Record of admin actions (create/update/delete user)."""

    __tablename__ = "admin_activity"
    __table_args__ = (
        Index("ix_admin_activity_performed_at", "performed_at"),
        Index("ix_admin_activity_admin_id", "admin_id"),
        Index("ix_admin_activity_action", "action"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    admin_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
