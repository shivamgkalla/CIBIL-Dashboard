"""customer view activity user viewed_at index

Revision ID: 65c82670370c
Revises: 8fa600f657f2
Create Date: 2026-03-17 14:59:09.224697

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '65c82670370c'
down_revision: Union[str, None] = '8fa600f657f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_customer_view_activity_user_viewed_at",
        "customer_view_activity",
        ["user_id", "viewed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_customer_view_activity_user_viewed_at",
        table_name="customer_view_activity",
    )
