"""membership_multiplier

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-12 00:00:00.000000+00:00

"""
import sqlalchemy as sa
from alembic import op

revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memberships",
        sa.Column("multiplier", sa.Numeric(5, 2), server_default="1", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("memberships", "multiplier")
