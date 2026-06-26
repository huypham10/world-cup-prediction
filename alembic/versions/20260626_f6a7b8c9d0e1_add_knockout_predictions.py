"""add knockout prediction support

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-26

Changes:
- matches: et_score_a, et_score_b, pk_score_a, pk_score_b, final_winner
- predictions: final_pick
- group_wagers: final_win_amount, final_loss_amount
- settlements: prediction_type column; swap unique constraint to include prediction_type
"""
from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- matches ---
    op.add_column("matches", sa.Column("et_score_a", sa.Integer(), nullable=True))
    op.add_column("matches", sa.Column("et_score_b", sa.Integer(), nullable=True))
    op.add_column("matches", sa.Column("pk_score_a", sa.Integer(), nullable=True))
    op.add_column("matches", sa.Column("pk_score_b", sa.Integer(), nullable=True))
    op.add_column("matches", sa.Column("final_winner", sa.String(10), nullable=True))

    # --- predictions ---
    op.add_column("predictions", sa.Column("final_pick", sa.String(10), nullable=True))

    # --- group_wagers ---
    op.add_column("group_wagers", sa.Column("final_win_amount", sa.Numeric(10, 2), nullable=True))
    op.add_column("group_wagers", sa.Column("final_loss_amount", sa.Numeric(10, 2), nullable=True))

    # --- settlements ---
    # Add prediction_type with a server default so existing rows get "90min"
    op.add_column(
        "settlements",
        sa.Column("prediction_type", sa.String(10), nullable=False, server_default="90min"),
    )
    # Drop old unique constraint, add new one that includes prediction_type
    op.drop_constraint("uq_settlement_group_user_match", "settlements", type_="unique")
    op.create_unique_constraint(
        "uq_settlement_group_user_match_type",
        "settlements",
        ["group_id", "user_id", "match_id", "prediction_type"],
    )


def downgrade() -> None:
    # --- settlements ---
    op.drop_constraint("uq_settlement_group_user_match_type", "settlements", type_="unique")
    op.create_unique_constraint(
        "uq_settlement_group_user_match",
        "settlements",
        ["group_id", "user_id", "match_id"],
    )
    op.drop_column("settlements", "prediction_type")

    # --- group_wagers ---
    op.drop_column("group_wagers", "final_loss_amount")
    op.drop_column("group_wagers", "final_win_amount")

    # --- predictions ---
    op.drop_column("predictions", "final_pick")

    # --- matches ---
    op.drop_column("matches", "final_winner")
    op.drop_column("matches", "pk_score_b")
    op.drop_column("matches", "pk_score_a")
    op.drop_column("matches", "et_score_b")
    op.drop_column("matches", "et_score_a")
