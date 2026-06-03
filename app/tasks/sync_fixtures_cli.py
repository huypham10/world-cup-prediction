"""CLI entry point for fixture sync only — no settlement."""
import asyncio
import logging

from app.config import settings
from app.database import AsyncSessionLocal
from app.football_client.client import BzzOiroClient
from app.football_client.sync import sync_fixtures

logger = logging.getLogger(__name__)


async def run() -> None:
    async with AsyncSessionLocal() as db:
        client = BzzOiroClient(
            api_key=settings.FOOTBALL_API_KEY,
            base_url=settings.FOOTBALL_API_BASE_URL,
            league_id=settings.FOOTBALL_LEAGUE_ID,
        )
        count = await sync_fixtures(db, client, settings.ROUND_DATE_RULES or None)
        logger.info("sync: %d new fixtures added (league %d)", count, settings.FOOTBALL_LEAGUE_ID)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
