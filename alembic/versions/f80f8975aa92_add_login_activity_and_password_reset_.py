"""add login activity and password reset tables

Revision ID: f80f8975aa92
Revises: 7163b7701c4b
Create Date: 2026-03-17 10:35:18.791558
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.

revision: str = 'f80f8975aa92'
down_revision: Union[str, None] = '7163b7701c4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Create login_activity table
    op.create_table(
        'login_activity',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('login_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ip_address', sa.String(length=64), nullable=True),
        sa.Column('user_agent', sa.String(length=512), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_login_activity_email', 'login_activity', ['email'], unique=False)
    op.create_index('ix_login_activity_id', 'login_activity', ['id'], unique=False)

    # Create password_reset_tokens table
    op.create_table(
        'password_reset_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=128), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_password_reset_tokens_id', 'password_reset_tokens', ['id'], unique=False)
    op.create_index('ix_password_reset_tokens_token_hash', 'password_reset_tokens', ['token_hash'], unique=False)


def downgrade() -> None:
    # Drop password_reset_tokens table
    op.drop_index('ix_password_reset_tokens_token_hash', table_name='password_reset_tokens')
    op.drop_index('ix_password_reset_tokens_id', table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')

    # Drop login_activity table
    op.drop_index('ix_login_activity_id', table_name='login_activity')
    op.drop_index('ix_login_activity_email', table_name='login_activity')
    op.drop_table('login_activity')
