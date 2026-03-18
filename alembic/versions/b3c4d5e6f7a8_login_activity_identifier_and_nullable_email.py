"""login activity identifier and nullable email

Revision ID: b3c4d5e6f7a8
Revises: 9a1c2b3d4e5f
Create Date: 2026-03-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "9a1c2b3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Add identifier as nullable for safe backfill
    op.add_column("login_activity", sa.Column("identifier", sa.String(length=255), nullable=True))

    # 2) Backfill identifier from existing email (historically email stored identifier-like values)
    op.execute("UPDATE login_activity SET identifier = COALESCE(email, 'unknown') WHERE identifier IS NULL")

    # 3) Enforce identifier NOT NULL
    op.alter_column("login_activity", "identifier", existing_type=sa.String(length=255), nullable=False)

    # 4) Allow email to be NULL for failed attempts going forward
    op.alter_column("login_activity", "email", existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    # Revert email back to NOT NULL (best-effort; may fail if NULLs exist)
    op.alter_column("login_activity", "email", existing_type=sa.String(length=255), nullable=False)
    op.drop_column("login_activity", "identifier")

