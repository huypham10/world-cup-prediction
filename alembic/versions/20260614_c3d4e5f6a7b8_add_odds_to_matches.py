"""add odds to matches

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("odds_a", sa.Numeric(6, 2), nullable=True))
    op.add_column("matches", sa.Column("odds_draw", sa.Numeric(6, 2), nullable=True))
    op.add_column("matches", sa.Column("odds_b", sa.Numeric(6, 2), nullable=True))
    op.add_column("matches", sa.Column("odds_fetched_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("matches", "odds_fetched_at")
    op.drop_column("matches", "odds_b")
    op.drop_column("matches", "odds_draw")
    op.drop_column("matches", "odds_a")
