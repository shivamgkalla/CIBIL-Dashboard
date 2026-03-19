"""ORM model for credit inquiry data."""

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InquiryData(Base):
    """Stores credit inquiry records per customer per snapshot."""

    __tablename__ = "inquiry_data"

    __table_args__ = (
        Index("ix_inquiry_data_customer_snapshot", "customer_id", "snapshot_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    customer_id: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True)
    inq_purp_cd: Mapped[str | None] = mapped_column(String(10), nullable=True)
    inq_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    m_sub_id: Mapped[str | None] = mapped_column(String(10), nullable=True)
    amount: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_id: Mapped[int | None] = mapped_column(index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
