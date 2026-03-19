"""ORM model for identity enrichment data."""

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IdentityData(Base):
    """Stores identity document details keyed by CUSTOMER_ID per snapshot."""

    __tablename__ = "identity_data"

    __table_args__ = (
        Index("ix_identity_data_customer_snapshot", "customer_id", "snapshot_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    customer_id: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True)
    pan: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    passport: Mapped[str | None] = mapped_column(String(20), nullable=True)
    voter_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    uid: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ration_card: Mapped[str | None] = mapped_column(Text, nullable=True)
    driving_license: Mapped[str | None] = mapped_column(String(30), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    snapshot_id: Mapped[int | None] = mapped_column(index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

