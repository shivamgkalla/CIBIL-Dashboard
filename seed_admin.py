"""One-time script to create the initial admin user.

Usage:
    python seed_admin.py

Reads DATABASE_URL and SECRET_KEY from environment / .env file.
If an admin already exists the script exits cleanly with no changes.
"""

import sys

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.database import SessionLocal
from app.models.user_model import User, UserRole

ADMIN_USERNAME = "admin"
ADMIN_EMAIL = "admin@cibil.local"
ADMIN_PASSWORD = "admin@123"


def seed(db: Session) -> None:
    existing = (
        db.query(User)
        .filter((User.role == UserRole.ADMIN))
        .first()
    )
    if existing:
        print(f"Admin already exists: {existing.username} ({existing.email})")
        return

    admin = User(
        username=ADMIN_USERNAME,
        email=ADMIN_EMAIL,
        hashed_password=hash_password(ADMIN_PASSWORD),
        role=UserRole.ADMIN,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    print(f"Admin created: {admin.username} / {admin.email}")
    print(f"Password: {ADMIN_PASSWORD}")
    print("IMPORTANT: Change this password immediately after first login.")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        seed(db)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()
