"""Service layer for admin action audit logging."""

from sqlalchemy.orm import Session

from app.models.admin_activity_model import AdminActivity


def log_admin_action(
    db: Session,
    *,
    admin_id: int,
    action: str,
    target_user_id: int | None = None,
    detail: str | None = None,
) -> None:
    """Record an admin action to the audit trail."""
    entry = AdminActivity(
        admin_id=admin_id,
        action=action,
        target_user_id=target_user_id,
        detail=detail,
    )
    db.add(entry)


def get_admin_activity(
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[AdminActivity]:
    """Return admin activity records ordered by most recent first."""
    return (
        db.query(AdminActivity)
        .order_by(AdminActivity.performed_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
