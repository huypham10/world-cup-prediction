"""
Fixture sync: fetch from football API and upsert into the matches table.
Called by both the web sync endpoint (step 4) and the poll-and-settle task (step 5).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.match import Match
from .client import FootballClientBase


def _compute_result(score_a: Optional[int], score_b: Optional[int]) -> Optional[str]:
    if score_a is None or score_b is None:
        return None
    if score_a > score_b:
        return "A"
    if score_b > score_a:
        return "B"
    return "draw"


async def sync_fixtures(db: AsyncSession, client: FootballClientBase) -> int:
    """
    Fetch upcoming fixtures from the API and upsert into the DB.
    Returns the number of newly inserted fixtures.
    Safe to call repeatedly — updates existing rows, does not duplicate.
    """
    fixtures = await client.fetch_upcoming_fixtures()
    new_count = 0

    for f in fixtures:
        result = await db.execute(
            select(Match).where(Match.external_id == f.external_id)
        )
        match = result.scalar_one_or_none()

        if match:
            match.status = f.status
            match.score_a = f.score_a
            match.score_b = f.score_b
            match.round_number = f.round_number
            match.round_name = f.round_name
            match.group_name = f.group_name
            if f.status == "finished" and match.result is None:
                match.result = _compute_result(f.score_a, f.score_b)
        else:
            db.add(
                Match(
                    external_id=f.external_id,
                    team_a=f.team_a,
                    team_b=f.team_b,
                    kickoff_time=f.kickoff_time,
                    status=f.status,
                    score_a=f.score_a,
                    score_b=f.score_b,
                    result=_compute_result(f.score_a, f.score_b)
                    if f.status == "finished"
                    else None,
                    round_number=f.round_number,
                    round_name=f.round_name,
                    group_name=f.group_name,
                )
            )
            new_count += 1

    await db.commit()
    return new_count
