"""create upload_errors table for bad row logging

Revision ID: c2a3f9b1d7e4
Revises: 8fa600f657f2
Create Date: 2026-03-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2a3f9b1d7e4"
down_revision: Union[str, None] = "8fa600f657f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upload_errors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("upload_id", sa.Integer(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("raw_data", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["upload_id"], ["upload_history.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_upload_errors_upload_id", "upload_errors", ["upload_id"], unique=False)
    op.create_index("ix_upload_errors_created_at", "upload_errors", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_upload_errors_created_at", table_name="upload_errors")
    op.drop_index("ix_upload_errors_upload_id", table_name="upload_errors")
    op.drop_table("upload_errors")

