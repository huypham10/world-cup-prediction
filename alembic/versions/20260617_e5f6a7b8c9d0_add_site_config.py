"""add site_config table

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-17

NOTE: depends on PR #11 (odds) being merged first — down_revision points to d4e5f6a7b8c9.
"""
from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("show_odds", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO site_config (id, show_odds) VALUES (1, true)")


def downgrade() -> None:
    op.drop_table("site_config")
