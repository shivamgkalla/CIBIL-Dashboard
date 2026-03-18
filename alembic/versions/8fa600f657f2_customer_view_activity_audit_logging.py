"""customer view activity audit logging

Revision ID: 8fa600f657f2
Revises: b3c4d5e6f7a8
Create Date: 2026-03-17 14:48:27.144404

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8fa600f657f2'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customer_view_activity",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.String(length=50), nullable=False),
        sa.Column(
            "viewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_customer_view_activity_customer_id",
        "customer_view_activity",
        ["customer_id"],
        unique=False,
    )
    op.create_index(
        "ix_customer_view_activity_user_id",
        "customer_view_activity",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_customer_view_activity_viewed_at",
        "customer_view_activity",
        ["viewed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_customer_view_activity_viewed_at", table_name="customer_view_activity")
    op.drop_index("ix_customer_view_activity_user_id", table_name="customer_view_activity")
    op.drop_index("ix_customer_view_activity_customer_id", table_name="customer_view_activity")
    op.drop_table("customer_view_activity")
