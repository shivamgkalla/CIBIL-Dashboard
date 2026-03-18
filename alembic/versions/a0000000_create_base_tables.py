"""create base tables (users, main_data, identity_data, upload_history)

These tables were originally created via create_all() before Alembic was
adopted.  This migration reproduces them so that a fresh database can be
bootstrapped entirely through ``alembic upgrade head``.

Revision ID: a000000base0
Revises:
Create Date: 2026-03-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a000000base0"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(50), unique=True, nullable=False, index=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("hashed_password", sa.Text, nullable=False),
        sa.Column(
            "role",
            sa.Enum("admin", "user", name="userrole"),
            nullable=False,
            server_default="user",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── upload_history ─────────────────────────────────────
    op.create_table(
        "upload_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("main_filename", sa.String(255), nullable=False),
        sa.Column("identity_filename", sa.String(255), nullable=False),
        sa.Column("records_inserted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("records_failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("uploaded_by", sa.Integer, nullable=True, index=True),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="success"),
    )

    # ── main_data ──────────────────────────────────────────
    op.create_table(
        "main_data",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("acct_key", sa.String(50), nullable=True, index=True),
        sa.Column("customer_id", sa.String(50), nullable=True, index=True),
        sa.Column("income", sa.Text, nullable=True),
        sa.Column("income_freq", sa.String(10), nullable=True),
        sa.Column("occup_status_cd", sa.String(10), nullable=True),
        sa.Column("rpt_dt", sa.String(10), nullable=True),
        sa.Column("bank_type", sa.String(10), nullable=True),
        sa.Column("snapshot_id", sa.Integer, nullable=True, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── identity_data ──────────────────────────────────────
    op.create_table(
        "identity_data",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.String(50), nullable=True, index=True),
        sa.Column("pan", sa.String(20), nullable=True),
        sa.Column("passport", sa.String(20), nullable=True),
        sa.Column("voter_id", sa.String(30), nullable=True),
        sa.Column("uid", sa.String(20), nullable=True),
        sa.Column("ration_card", sa.Text, nullable=True),
        sa.Column("driving_license", sa.String(30), nullable=True),
        sa.Column("snapshot_id", sa.Integer, nullable=True, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("identity_data")
    op.drop_table("main_data")
    op.drop_table("upload_history")
    op.drop_table("users")
