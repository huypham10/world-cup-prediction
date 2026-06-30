"""
Re-settle finished matches using the current wager settings.

Usage:
    python -m app.tasks.resettle <group_id>   # one group
    python -m app.tasks.resettle --all        # all groups
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
        result = await db.execute(
            delete(Settlement).where(Settlement.group_id == group_id)
        )
        logger.info("resettle: deleted %d existing settlement rows", result.rowcount)

        await db.execute(
            update(Match)
            .where(Match.status == "finished", Match.result.is_not(None))
            .values(settled=False)
        )
        await db.commit()
        logger.info("resettle: reset settled flag on finished matches")

        await settle(db)

    logger.info("resettle: done")


async def run_all() -> None:
    logger.info("resettle: starting for all groups")

    async with AsyncSessionLocal() as db:
        result = await db.execute(delete(Settlement))
        logger.info("resettle: deleted %d existing settlement rows", result.rowcount)

        await db.execute(
            update(Match)
            .where(Match.status == "finished", Match.result.is_not(None))
            .values(settled=False)
        )
        await db.commit()
        logger.info("resettle: reset settled flag on finished matches")

        await settle(db)

    logger.info("resettle: done")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--all":
        logging.basicConfig(level=logging.INFO)
        asyncio.run(run_all())
    elif len(sys.argv) == 2 and sys.argv[1].isdigit():
        logging.basicConfig(level=logging.INFO)
        asyncio.run(run(int(sys.argv[1])))
    else:
        print("Usage: python -m app.tasks.resettle <group_id>")
        print("       python -m app.tasks.resettle --all")
        sys.exit(1)
