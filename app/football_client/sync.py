"""
Fixture sync: fetch from football API and upsert into the matches table.
Called by both the web sync endpoint and the poll-and-settle task.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.group_wager import TOURNAMENT_ROUNDS
from ..models.match import Match
from .client import BzzOiroClient, FixtureData, FootballClientBase


_KNOCKOUT_ROUND_NAMES = set(TOURNAMENT_ROUNDS) - {"Group Stage"}


def _compute_result(score_a: Optional[int], score_b: Optional[int]) -> Optional[str]:
    if score_a is None or score_b is None:
        return None
    if score_a > score_b:
        return "A"
    if score_b > score_a:
        return "B"
    return "draw"


def _compute_final_winner(
    score_a: Optional[int],
    score_b: Optional[int],
    et_score_a: Optional[int],
    et_score_b: Optional[int],
    pk_score_a: Optional[int],
    pk_score_b: Optional[int],
) -> Optional[str]:
    """Return "A" or "B" for the outright winner of a knockout match, or None if
    the winner cannot yet be determined from the available score data.

    Resolution order:
      1. 90-minute result — if not a draw, that team wins outright.
      2. Extra time — missing ET scores are treated as 0-0 (some APIs omit them
         when the match went straight to penalties with no ET goals).
      3. Penalties — only checked when AET totals are equal.

    Returns None when 90-min scores are unavailable, or when the match was a draw
    through AET and no penalty scores have been received yet.
    """
    # 90-minute result
    if score_a is not None and score_b is not None and score_a != score_b:
        return "A" if score_a > score_b else "B"
    # Extra time — only reached if 90-min was a draw; treat missing ET scores as 0-0
    if score_a is not None and score_b is not None:
        aet_total_a = score_a + (et_score_a or 0)
        aet_total_b = score_b + (et_score_b or 0)
        if aet_total_a != aet_total_b:
            return "A" if aet_total_a > aet_total_b else "B"
        # Penalties — only reached if AET was also a draw
        if pk_score_a is not None and pk_score_b is not None:
            return "A" if pk_score_a > pk_score_b else "B"
    return None


def _is_knockout(f: FixtureData) -> bool:
    """True when the fixture is a knockout-round match."""
    if f.round_name and f.round_name in _KNOCKOUT_ROUND_NAMES:
        return True
    if f.round_number is not None:
        return f.round_number >= 4
    return False


def is_knockout_match(match: "Match") -> bool:
    """True when the DB match row is a knockout-round match."""
    if match.round_name and match.round_name in _KNOCKOUT_ROUND_NAMES:
        return True
    if match.round_number is not None:
        return match.round_number >= 4
    return False


def _apply_round_rules(
    kickoff_time: datetime, rules: list[dict[str, str]]
) -> Optional[str]:
    """
    Map a kickoff date to a round name using date-range rules.
    Used in staging for leagues that return empty round_name from the API,
    to simulate the World Cup round structure with a live active league.
    Rules are checked in order; the first match wins.
    Each rule: {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD", "name": "Round name"}
    """
    date_str = kickoff_time.date().isoformat()
    for rule in rules:
        if rule.get("from", "") <= date_str <= rule.get("to", ""):
            return rule["name"]
    return None


async def sync_fixtures(
    db: AsyncSession,
    client: FootballClientBase,
    round_date_rules: Optional[list[dict[str, str]]] = None,
) -> int:
    """
    Fetch upcoming fixtures from the API and upsert into the DB.
    After syncing, deletes unsettled matches that belong to a different league
    so switching FOOTBALL_LEAGUE_ID keeps the DB clean.
    Returns (new_count, newly_finished).

    result vs final_winner:
      - result: 90-minute outcome ("A", "B", or "draw"). Write-once — set when the
        match first transitions to finished and never overwritten.
      - final_winner: outright winner after ET/penalties ("A" or "B", knockout only).
        Also write-once once set, but filled in lazily — if the API doesn't return
        ET/pens scores in the same response that marks the match finished, subsequent
        syncs will keep trying until _compute_final_winner returns a non-None value.
        Missing ET scores are treated as 0-0 so penalty data alone is sufficient.

    newly_finished increments on two events:
      1. result transitions from None (match just finished).
      2. final_winner transitions from None to a value for a knockout match.
    Both events trigger settlement in the caller.

    round_date_rules: optional date-range → round-name mapping applied when the
    API returns an empty round_name. Set via ROUND_DATE_RULES in .env (staging only).
    """
    league_id = client.league_id if isinstance(client, BzzOiroClient) else None
    fixtures = await client.fetch_upcoming_fixtures()
    new_count = 0
    newly_finished = 0

    for f in fixtures:
        # Apply date-based round rules when the API provides no round name
        effective_round_name = f.round_name
        if not effective_round_name and round_date_rules:
            effective_round_name = _apply_round_rules(f.kickoff_time, round_date_rules)

        result = await db.execute(
            select(Match).where(Match.external_id == f.external_id)
        )
        match = result.scalar_one_or_none()

        knockout = _is_knockout(f)

        if match:
            # Existing match — update mutable fields on every sync.
            # Team names and kickoff_time can change for knockout placeholders
            # (e.g. "Winner Match 42") until the previous round is settled.
            match.team_a = f.team_a
            match.team_b = f.team_b
            match.kickoff_time = f.kickoff_time
            match.status = f.status
            match.score_a = f.score_a
            match.score_b = f.score_b
            match.et_score_a = f.et_score_a
            match.et_score_b = f.et_score_b
            match.pk_score_a = f.pk_score_a
            match.pk_score_b = f.pk_score_b
            match.round_number = f.round_number
            match.round_name = effective_round_name
            match.group_name = f.group_name
            match.league_id = league_id
            if f.status == "finished":
                # result is write-once: set on first finished sync, never overwritten.
                if match.result is None:
                    match.result = _compute_result(f.score_a, f.score_b)
                    newly_finished += 1
                # final_winner is filled in lazily: ET/pens data may arrive in a later
                # API response than the one that first marked the match finished.
                if knockout and match.final_winner is None:
                    match.final_winner = _compute_final_winner(
                        f.score_a, f.score_b, f.et_score_a, f.et_score_b, f.pk_score_a, f.pk_score_b,
                    )
                    if match.final_winner is not None:
                        newly_finished += 1
        else:
            # New fixture — insert for the first time.
            # Pre-compute final_winner in case the app was offline when the match
            # was played and the API returns it already finished.
            final_winner = None
            if f.status == "finished" and knockout:
                final_winner = _compute_final_winner(
                    f.score_a, f.score_b, f.et_score_a, f.et_score_b, f.pk_score_a, f.pk_score_b,
                )
            db.add(
                Match(
                    external_id=f.external_id,
                    team_a=f.team_a,
                    team_b=f.team_b,
                    kickoff_time=f.kickoff_time,
                    status=f.status,
                    score_a=f.score_a,
                    score_b=f.score_b,
                    et_score_a=f.et_score_a,
                    et_score_b=f.et_score_b,
                    pk_score_a=f.pk_score_a,
                    pk_score_b=f.pk_score_b,
                    result=_compute_result(f.score_a, f.score_b) if f.status == "finished" else None,
                    final_winner=final_winner,
                    round_number=f.round_number,
                    round_name=effective_round_name,
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
    return new_count, newly_finished
