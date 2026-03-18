"""Service layer for login activity logging."""

from sqlalchemy.orm import Session

from app.models.login_activity_model import LoginActivity


def log_login_attempt(
    db: Session,
    identifier: str,
    email: str | None,
    success: bool,
    user_id: int | None,
    ip_address: str | None,
    user_agent: str | None,
    failure_reason: str | None = None,
) -> LoginActivity:
    """
    Add a login attempt record to the current transaction.

    Note: This function does NOT commit; caller controls transaction boundaries.
    """
    record = LoginActivity(
        user_id=user_id,
        identifier=identifier,
        email=email,
        ip_address=ip_address,
        user_agent=user_agent,
        success=success,
        failure_reason=failure_reason if not success else None,
    )
    db.add(record)
    db.flush()
    return record


def get_login_activity(db: Session, *, limit: int = 50, offset: int = 0) -> list[LoginActivity]:
    """Return login attempts ordered by time descending with pagination."""
    return (
        db.query(LoginActivity)
        .order_by(LoginActivity.login_time.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

