"""login activity failure reason and indexes

Revision ID: 9a1c2b3d4e5f
Revises: f80f8975aa92
Create Date: 2026-03-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9a1c2b3d4e5f"
down_revision: Union[str, None] = "f80f8975aa92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "login_activity",
        sa.Column("failure_reason", sa.String(length=64), nullable=True),
    )

    op.create_index(
        "ix_login_activity_login_time",
        "login_activity",
        ["login_time"],
        unique=False,
    )
    op.create_index(
        "ix_login_activity_email_login_time",
        "login_activity",
        ["email", "login_time"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_login_activity_email_login_time", table_name="login_activity")
    op.drop_index("ix_login_activity_login_time", table_name="login_activity")
    op.drop_column("login_activity", "failure_reason")

