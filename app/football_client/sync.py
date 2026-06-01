"""
Fixture sync: fetch from football API and upsert into the matches table.
Called by both the web sync endpoint and the poll-and-settle task.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.match import Match
from .client import BzzOiroClient, FootballClientBase


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
    After syncing, deletes unsettled matches that belong to a different league
    so switching FOOTBALL_LEAGUE_ID keeps the DB clean.
    Returns the number of newly inserted fixtures.
    """
    league_id = client.league_id if isinstance(client, BzzOiroClient) else None
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
            match.league_id = league_id
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
                    league_id=league_id,
                )
            )
            new_count += 1

    # Remove unsettled matches from other leagues so the active league stays clean.
    # Settled matches are kept — they hold historical settlement records.
    if league_id is not None:
        await db.execute(
            delete(Match).where(
                Match.league_id != league_id,
                Match.settled.is_(False),
            )
        )

    await db.commit()
    return new_count
