"""add index for snapshot and bank_type dashboard query

Revision ID: 7163b7701c4b
Revises: d0bb8cb3f7b5
Create Date: 2026-03-16 18:25:40.431839

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7163b7701c4b'
down_revision: Union[str, None] = 'd0bb8cb3f7b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_main_data_snapshot_bank",
        "main_data",
        ["snapshot_id", "bank_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_main_data_snapshot_bank",
        table_name="main_data",
    )
