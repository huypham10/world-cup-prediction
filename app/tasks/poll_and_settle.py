"""
Poll-and-settle task. Runs independently of the web server.

Each run:
  1. Sync fixtures from the football API (fetch + upsert into matches table).
  2. For each finished, unsettled match that has a result:
     a. For every group: settle all members who have a prediction for the match
        (regardless of join time) plus members who joined before kickoff with no
        prediction (auto-loss). Late joiners with no prediction are excluded unless
        the group's late_join_counts_as_loss flag is set (then auto-loss).
        Per-round wager used for amounts. No wager = NULL amount.
        Uses INSERT ON CONFLICT DO NOTHING.
     b. Mark match.settled = True and commit.
  3. Exit. Idempotent — re-running on the same data produces no duplicate rows.

Prediction locking is NOT done here. The /matches/{id}/predict endpoint checks
match.kickoff_time <= now on every request — that is the authoritative lock.

CLI:  python -m app.tasks.poll_and_settle
HTTP: POST /tasks/poll  (guarded by X-Task-Secret — see app/routers/tasks.py)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.football_client.client import BzzOiroClient
from app.football_client.sync import sync_fixtures
from app.models.group import Group
from app.models.group_wager import GroupWager
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


def _round_label(match: Match) -> str:
    return match.round_name if match.round_name else "Group Stage"


def _wager_amount(
    wager: Optional[GroupWager], correct: bool
) -> Optional[Decimal]:
    if wager is None:
        return None
    if correct:
        return wager.win_amount
    return -wager.loss_amount if wager.loss_amount is not None else None


async def _settle_match(
    db: AsyncSession,
    match: Match,
    wagers_by_group_round: dict[tuple[int, str], GroupWager],
) -> int:
    """
    Create Settlement rows for every eligible group member for one finished match.
    A member who predicted before kickoff always counts, regardless of when they joined.
    A member who joined late AND has no prediction is excluded (or auto-loss if the
    group's late_join_counts_as_loss toggle is on).
    Returns the number of new rows inserted (0 if already settled).
    """
    now = datetime.now(timezone.utc)
    round_label = _round_label(match)
    created = 0

    groups_result = await db.execute(select(Group))
    groups = groups_result.scalars().all()

    for group in groups:
        wager = wagers_by_group_round.get((group.id, round_label))

        members_result = await db.execute(
            select(Membership).where(Membership.group_id == group.id)
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

            # A prediction existing means it was made before kickoff (lock is enforced
            # at the endpoint). Late joiners who predicted play fairly — use their pick.
            # The toggle only governs late joiners who have no prediction at all.
            joined_late = member.joined_at >= match.kickoff_time
            if joined_late and prediction is None:
                if not group.late_join_counts_as_loss:
                    continue  # exclude from this match entirely
                # else: fall through to auto-loss below

            correct = prediction is not None and prediction.pick == match.result
            amount = _wager_amount(wager, correct)

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


async def settle(db: AsyncSession) -> None:
    """Run settlement only — no fixture sync. Used by resettle and called from run()."""
    wagers_result = await db.execute(select(GroupWager))
    wagers_by_group_round: dict[tuple[int, str], GroupWager] = {
        (w.group_id, w.round_name): w for w in wagers_result.scalars().all()
    }

    result = await db.execute(
        select(Match).where(
            Match.status == "finished",
            Match.settled.is_(False),
            Match.result.is_not(None),
        )
    )
    unsettled = result.scalars().all()
    logger.info("settle: %d matches to settle", len(unsettled))

    for match in unsettled:
        count = await _settle_match(db, match, wagers_by_group_round)
        match.settled = True
        await db.commit()
        logger.info(
            "settle: %s vs %s (match %s) — %d rows",
            match.team_a, match.team_b, match.id, count,
        )


async def run() -> None:
    logger.info("poll_and_settle: starting")

    async with AsyncSessionLocal() as db:
        client = _make_client()
        new_fixtures = await sync_fixtures(db, client, settings.round_date_rules or None)
        logger.info("poll_and_settle: %d new fixtures synced", new_fixtures)
        await settle(db)

    logger.info("poll_and_settle: done")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
