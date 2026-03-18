"""fix userrole enum values to lowercase

Revision ID: f78a6a4d432e
Revises: 6211d379e736
Create Date: 2026-03-18 18:08:13.145458

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f78a6a4d432e'
down_revision: Union[str, None] = '6211d379e736'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Convert existing uppercase data to lowercase using a temporary text column.
    # PostgreSQL enums cannot be renamed in-place, so we:
    # 1. Change column to text
    # 2. Lowercase existing values
    # 3. Drop old enum type
    # 4. Create new enum with lowercase values
    # 5. Convert column back to enum
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE text")
    op.execute("UPDATE users SET role = LOWER(role)")
    op.execute("DROP TYPE userrole")
    op.execute("CREATE TYPE userrole AS ENUM ('admin', 'user')")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE userrole USING role::userrole")


def downgrade() -> None:
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE text")
    op.execute("UPDATE users SET role = UPPER(role)")
    op.execute("DROP TYPE userrole")
    op.execute("CREATE TYPE userrole AS ENUM ('ADMIN', 'USER')")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE userrole USING role::userrole")
