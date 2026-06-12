"""unique_user_name — normalize existing names to NFC then add unique constraint

Revision ID: a1b2c3d4e5f6
Revises: b62279727c14
Create Date: 2026-06-12 00:00:00.000000+00:00

"""
import unicodedata
from alembic import op
from sqlalchemy import text

revision = 'a1b2c3d4e5f6'
down_revision = 'b62279727c14'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Normalize all stored names to NFC so Vietnamese characters entered from
    # different keyboards/browsers map to the same bytes before we add the
    # unique constraint (which would fail if any NFD/NFC duplicates exist).
    rows = conn.execute(text("SELECT id, name FROM users")).fetchall()
    for user_id, name in rows:
        normalized = unicodedata.normalize("NFC", name)
        if normalized != name:
            conn.execute(
                text("UPDATE users SET name = :n WHERE id = :id"),
                {"n": normalized, "id": user_id},
            )

    op.create_unique_constraint("uq_users_name", "users", ["name"])


def downgrade() -> None:
    op.drop_constraint("uq_users_name", "users", type_="unique")
