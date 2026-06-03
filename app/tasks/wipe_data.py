"""
Wipe all user data from a target database while preserving the schema and
alembic_version. Designed for initialising a prod/staging Neon branch that
was cloned from a dev branch containing test data.

DESTRUCTIVE — irreversible. Double-check the URL before running.

Usage:
    python -m app.tasks.wipe_data <database_url>

The URL can use the asyncpg or psycopg2 scheme — it is normalised automatically.
"""
import re
import sys

import psycopg2

# Tables in FK-safe order (children before parents).
# alembic_version is intentionally excluded — the schema stays intact.
_TABLES = [
    "settlements",
    "predictions",
    "group_wagers",
    "memberships",
    "matches",
    "groups",
    "users",
]


def _sync_url(url: str) -> str:
    """Normalise any variant of the Postgres URL to a psycopg2-compatible one."""
    url = re.sub(r"\+asyncpg", "", url)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    # Strip sslmode from URL and rely on sslrootcert default; psycopg2 handles it
    return url


def wipe(url: str) -> None:
    conn = psycopg2.connect(_sync_url(url))
    conn.autocommit = True
    cur = conn.cursor()

    tables = ", ".join(_TABLES)
    cur.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE;")
    print(f"Wiped and reset sequences: {tables}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m app.tasks.wipe_data <database_url>")
        sys.exit(1)

    target = sys.argv[1]
    print(f"Target: {target[:40]}...")
    confirm = input("Type 'yes' to wipe all user data: ").strip()
    if confirm != "yes":
        print("Aborted.")
        sys.exit(0)

    wipe(target)
    print("Done.")
