"""One-time script to create the initial admin user.

Usage:
    ADMIN_USERNAME=admin ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=s3cret python seed_admin.py

Credentials are read from environment variables.
If an admin already exists the script exits cleanly with no changes.
"""

import os
import sys

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.database import SessionLocal
from app.models.user_model import User, UserRole


def seed(db: Session) -> None:
    username = os.environ.get("ADMIN_USERNAME")
    email = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")

    if not all([username, email, password]):
        print("Skipping admin seed — set ADMIN_USERNAME, ADMIN_EMAIL, and ADMIN_PASSWORD env vars to create one.")
        return

    existing = (
        db.query(User)
        .filter((User.role == UserRole.ADMIN))
        .first()
    )
    if existing:
        print(f"Admin already exists: {existing.username} ({existing.email})")
        return

    admin = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        role=UserRole.ADMIN,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    print(f"Admin created: {admin.username} / {admin.email}")
    print("IMPORTANT: Change this password after first login.")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        seed(db)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()
