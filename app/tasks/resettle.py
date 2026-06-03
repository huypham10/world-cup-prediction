"""
Re-settle all finished matches for a specific group using the current wager settings.

Clears existing settlement rows and the settled flag for all finished matches,
then runs settlement — no fixture sync.

Usage:
    python -m app.tasks.resettle <group_id>
"""
import asyncio
import logging
import sys

from sqlalchemy import delete, update

from app.database import AsyncSessionLocal
from app.models.match import Match
from app.models.settlement import Settlement
from app.tasks.poll_and_settle import settle

logger = logging.getLogger(__name__)


async def run(group_id: int) -> None:
    logger.info("resettle: starting for group %d", group_id)

    async with AsyncSessionLocal() as db:
        # Delete all settlement rows for this group
        result = await db.execute(
            delete(Settlement).where(Settlement.group_id == group_id)
        )
        logger.info("resettle: deleted %d existing settlement rows", result.rowcount)

        # Reset settled=False on finished matches that had settlements for this group
        # We reset ALL finished matches so they get re-examined by settle()
        await db.execute(
            update(Match)
            .where(Match.status == "finished", Match.result.is_not(None))
            .values(settled=False)
        )
        await db.commit()
        logger.info("resettle: reset settled flag on finished matches")

        # Re-run settlement (no sync)
        await settle(db)

    logger.info("resettle: done")


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print("Usage: python -m app.tasks.resettle <group_id>")
        sys.exit(1)
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(int(sys.argv[1])))
