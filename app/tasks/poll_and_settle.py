"""
Poll-and-settle task. Runs independently of the web server.

Each run:
  1. Sync fixtures from the football API (fetch + upsert into matches table).
  2. Lock predictions for all matches that have kicked off (bulk UPDATE).
  3. For each finished, unsettled match that has a result:
     a. For every group: settle members who joined BEFORE kickoff.
        No prediction = automatic loss (forfeit). Uses INSERT ON CONFLICT DO NOTHING.
     b. Mark match.settled = True and commit.
  4. Exit. Idempotent — re-running on the same data produces no duplicate rows.

CLI:  python -m app.tasks.poll_and_settle
HTTP: POST /tasks/poll  (guarded by X-Task-Secret — see app/routers/tasks.py)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.football_client.client import BzzOiroClient
from app.football_client.sync import sync_fixtures
from app.models.group import Group
from app.models.match import Match
from app.models.membership import Membership
from app.models.prediction import Prediction
from app.models.settlement import Settlement

logger = logging.getLogger(__name__)


def _make_client() -> BzzOiroClient:
    return BzzOiroClient(
        api_key=settings.FOOTBALL_API_KEY,
        base_url=settings.FOOTBALL_API_BASE_URL,
        league_id=settings.FOOTBALL_LEAGUE_ID,
    )


async def _lock_predictions(db: AsyncSession) -> int:
    """Bulk-lock predictions for matches that have already kicked off."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(Prediction)
        .where(
            Prediction.locked.is_(False),
            Prediction.match_id.in_(
                select(Match.id).where(Match.kickoff_time <= now)
            ),
        )
        .values(locked=True)
    )
    return result.rowcount


async def _settle_match(db: AsyncSession, match: Match) -> int:
    """
    Create Settlement rows for every eligible group member for one finished match.
    Eligible = membership.joined_at < match.kickoff_time.
    Returns the number of new rows inserted (0 if already settled).
    """
    now = datetime.now(timezone.utc)
    created = 0

    groups_result = await db.execute(select(Group))
    groups = groups_result.scalars().all()

    for group in groups:
        # Only members who joined before kickoff are eligible
        members_result = await db.execute(
            select(Membership).where(
                Membership.group_id == group.id,
                Membership.joined_at < match.kickoff_time,
            )
        )
        members = members_result.scalars().all()

        for member in members:
            pred_result = await db.execute(
                select(Prediction).where(
                    Prediction.user_id == member.user_id,
                    Prediction.match_id == match.id,
                )
            )
            prediction = pred_result.scalar_one_or_none()

            # No prediction = automatic forfeit
            correct = prediction is not None and prediction.pick == match.result

            amount = None
            if group.stake is not None:
                amount = group.stake if correct else -group.stake

            stmt = (
                pg_insert(Settlement)
                .values(
                    group_id=group.id,
                    user_id=member.user_id,
                    match_id=match.id,
                    correct=correct,
                    amount=amount,
                    created_at=now,
                )
                .on_conflict_do_nothing()
            )
            result = await db.execute(stmt)
            created += result.rowcount

    return created


async def run() -> None:
    logger.info("poll_and_settle: starting")

    async with AsyncSessionLocal() as db:
        # 1. Sync fixtures
        client = _make_client()
        new_fixtures = await sync_fixtures(db, client)
        logger.info("poll_and_settle: %d new fixtures synced", new_fixtures)

        # 2. Lock predictions for started matches
        locked = await _lock_predictions(db)
        if locked:
            await db.commit()
            logger.info("poll_and_settle: locked %d predictions", locked)

        # 3. Settle finished, unsettled matches
        result = await db.execute(
            select(Match).where(
                Match.status == "finished",
                Match.settled.is_(False),
                Match.result.is_not(None),
            )
        )
        unsettled = result.scalars().all()
        logger.info("poll_and_settle: %d matches to settle", len(unsettled))

        for match in unsettled:
            count = await _settle_match(db, match)
            match.settled = True
            await db.commit()
            logger.info(
                "poll_and_settle: settled %s vs %s (match %s) — %d settlement rows",
                match.team_a,
                match.team_b,
                match.id,
                count,
            )

    logger.info("poll_and_settle: done")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
