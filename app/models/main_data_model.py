"""ORM model for main CIBIL data file."""

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MainData(Base):
    """Stores core account-level CIBIL data for each snapshot row."""

    __tablename__ = "main_data"

    __table_args__ = (
        Index("ix_main_data_customer_snapshot", "customer_id", "snapshot_id"),
        Index("ix_main_data_occup_status_cd", "occup_status_cd"),
        Index("ix_main_data_rpt_dt", "rpt_dt"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    acct_key: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True)
    income: Mapped[str | None] = mapped_column(Text, nullable=True)
    income_freq: Mapped[str | None] = mapped_column(String(10), nullable=True)
    occup_status_cd: Mapped[str | None] = mapped_column(String(10), nullable=True)
    rpt_dt: Mapped[str | None] = mapped_column(String(10), nullable=True)
    bank_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    credit_score: Mapped[str | None] = mapped_column(String(10), nullable=True)
    full_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    dob: Mapped[str | None] = mapped_column(String(20), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)
    snapshot_id: Mapped[int | None] = mapped_column(index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

