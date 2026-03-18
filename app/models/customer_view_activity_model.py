"""Customer view audit logging ORM model."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CustomerViewActivity(Base):
    """Record of a user viewing a customer."""

    __tablename__ = "customer_view_activity"
    __table_args__ = (
        Index("ix_customer_view_activity_user_id", "user_id"),
        Index("ix_customer_view_activity_customer_id", "customer_id"),
        Index("ix_customer_view_activity_viewed_at", "viewed_at"),
        Index("ix_customer_view_activity_user_viewed_at", "user_id", "viewed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
    )
    customer_id: Mapped[str] = mapped_column(String(50), nullable=False)
    viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

