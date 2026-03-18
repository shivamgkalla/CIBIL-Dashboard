"""merge heads: upload errors + customer view index

Revision ID: df4b1b2c0a11
Revises: 65c82670370c, c2a3f9b1d7e4
Create Date: 2026-03-17
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "df4b1b2c0a11"
down_revision: Union[str, Sequence[str], None] = ("65c82670370c", "c2a3f9b1d7e4")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge migration: no schema changes.
    pass


def downgrade() -> None:
    # Merge migration: no schema changes.
    pass

