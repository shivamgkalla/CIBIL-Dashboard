"""add admin_activity table and last_login to users

Revision ID: 6211d379e736
Revises: 0bcf7ab68f09
Create Date: 2026-03-18 18:01:54.773708

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6211d379e736'
down_revision: Union[str, None] = '0bcf7ab68f09'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('admin_activity',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('admin_id', sa.Integer(), nullable=False),
    sa.Column('action', sa.String(length=50), nullable=False),
    sa.Column('target_user_id', sa.Integer(), nullable=True),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.Column('performed_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['admin_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_admin_activity_action', 'admin_activity', ['action'], unique=False)
    op.create_index('ix_admin_activity_admin_id', 'admin_activity', ['admin_id'], unique=False)
    op.create_index(op.f('ix_admin_activity_id'), 'admin_activity', ['id'], unique=False)
    op.create_index('ix_admin_activity_performed_at', 'admin_activity', ['performed_at'], unique=False)
    op.add_column('users', sa.Column('last_login', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'last_login')
    op.drop_index('ix_admin_activity_performed_at', table_name='admin_activity')
    op.drop_index(op.f('ix_admin_activity_id'), table_name='admin_activity')
    op.drop_index('ix_admin_activity_admin_id', table_name='admin_activity')
    op.drop_index('ix_admin_activity_action', table_name='admin_activity')
    op.drop_table('admin_activity')
