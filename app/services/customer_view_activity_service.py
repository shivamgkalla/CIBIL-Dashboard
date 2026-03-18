"""Service layer for customer view activity audit logging."""

from sqlalchemy.orm import Session

from app.models.customer_view_activity_model import CustomerViewActivity


def log_customer_view(db: Session, user_id: int, customer_id: str) -> CustomerViewActivity:
    """
    Add a customer view record to the current transaction.

    Note: This function does NOT commit; caller controls transaction boundaries.
    """
    record = CustomerViewActivity(user_id=user_id, customer_id=customer_id)
    db.add(record)
    db.flush()
    return record


def get_customer_view_activity(
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[CustomerViewActivity]:
    """Return customer view logs ordered by time descending with pagination."""
    return (
        db.query(CustomerViewActivity)
        .order_by(CustomerViewActivity.viewed_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

