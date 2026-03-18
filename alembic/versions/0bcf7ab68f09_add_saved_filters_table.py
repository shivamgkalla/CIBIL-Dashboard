"""add saved_filters table

Revision ID: 0bcf7ab68f09
Revises: df4b1b2c0a11
Create Date: 2026-03-17 16:15:30.084726

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0bcf7ab68f09'
down_revision: Union[str, None] = 'df4b1b2c0a11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "saved_filters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_saved_filters_user_id", "saved_filters", ["user_id"], unique=False)
    op.create_index("ix_saved_filters_created_at", "saved_filters", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_saved_filters_created_at", table_name="saved_filters")
    op.drop_index("ix_saved_filters_user_id", table_name="saved_filters")
    op.drop_table("saved_filters")
