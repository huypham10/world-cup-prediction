from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.group import Group
from ..models.group_wager import GroupWager, TOURNAMENT_ROUNDS
from ..models.match import Match
from ..models.membership import Membership
from ..models.prediction import Prediction
from ..models.settlement import Settlement
from ..models.user import User
from ..templates import templates

router = APIRouter()


def _round_label(match: Match) -> str:
    return match.round_name if match.round_name else "Group Stage"


async def _require_member(db: AsyncSession, group_id: int, user_id: int) -> None:
    result = await db.execute(
        select(Membership).where(
            Membership.group_id == group_id,
            Membership.user_id == user_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="You are not a member of this group")


@router.get("/groups/{group_id}/scoreboard")
async def scoreboard(
    request: Request,
    group_id: int,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user:
        return RedirectResponse("/login", status_code=302)

    await _require_member(db, group_id, current_user.id)

    group = await db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # All groups the current user belongs to (for the group switcher)
    all_groups_result = await db.execute(
        select(Group)
        .join(Membership, Membership.group_id == Group.id)
        .where(Membership.user_id == current_user.id)
        .order_by(Group.name)
    )
    all_groups = all_groups_result.scalars().all()

    # All members of this group with their multipliers, ordered by name
    members_result = await db.execute(
        select(User, Membership.multiplier)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.group_id == group_id)
        .order_by(User.name)
    )
    member_rows = members_result.all()
    members = [row[0] for row in member_rows]
    multiplier_by_user: dict[int, Decimal] = {row[0].id: row[1] for row in member_rows}
    member_ids = [u.id for u in members]

    # All settlements for this group — single query
    all_settlements_result = await db.execute(
        select(Settlement).where(Settlement.group_id == group_id)
    )
    all_settlements = all_settlements_result.scalars().all()

    settled_match_ids = {s.match_id for s in all_settlements}

    # Load settled matches + predictions in two queries
    matches_by_id: dict[int, Match] = {}
    preds_by_match_user: dict[tuple[int, int], Prediction] = {}
    match_rows = []

    if settled_match_ids:
        matches_result = await db.execute(
            select(Match)
            .where(Match.id.in_(settled_match_ids))
            .order_by(Match.kickoff_time.desc())
        )
        settled_matches = matches_result.scalars().all()
        matches_by_id = {m.id: m for m in settled_matches}

        preds_result = await db.execute(
            select(Prediction).where(
                Prediction.match_id.in_(settled_match_ids),
                Prediction.user_id.in_(member_ids),
            )
        )
        preds_by_match_user = {
            (p.match_id, p.user_id): p for p in preds_result.scalars().all()
        }

        # Index settlements by (match_id, user_id) for match history
        by_match_user: dict[tuple[int, int], Settlement] = {
            (s.match_id, s.user_id): s for s in all_settlements
        }

        for match in settled_matches:
            member_results = []
            for user in members:
                s = by_match_user.get((match.id, user.id))
                p = preds_by_match_user.get((match.id, user.id))
                if s is None:
                    member_results.append({
                        "user": user, "pick": None,
                        "correct": None, "amount": None, "eligible": False,
                    })
                else:
                    member_results.append({
                        "user": user,
                        "pick": p.pick if p else None,
                        "correct": s.correct,
                        "amount": s.amount,
                        "eligible": True,
                    })
            match_rows.append({"match": match, "member_results": member_results})

    # Overall standings — aggregate across all settlements per user
    by_user: dict[int, list[Settlement]] = {u.id: [] for u in members}
    for s in all_settlements:
        by_user.setdefault(s.user_id, []).append(s)

    def _stats(settlements: list[Settlement], multiplier: Decimal = Decimal("1")) -> dict:
        correct = sum(1 for s in settlements if s.correct)
        wrong = sum(1 for s in settlements if not s.correct)
        raw_net = sum((s.amount for s in settlements if s.amount is not None), Decimal(0))
        net = (raw_net * multiplier).quantize(Decimal("0.01"))
        return {"correct": correct, "wrong": wrong, "played": len(settlements), "net": net}

    standings = sorted(
        [{"user": u, **_stats(by_user.get(u.id, []), multiplier_by_user.get(u.id, Decimal("1")))} for u in members],
        key=lambda x: (x["correct"], x["net"]),
        reverse=True,
    )

    # Round standings — group settlements by round, sorted most recent first
    # max kickoff per round drives the sort order
    round_kickoff: dict[str, datetime] = {}
    round_settlements: dict[str, dict[int, list[Settlement]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for s in all_settlements:
        match = matches_by_id.get(s.match_id)
        if not match:
            continue
        label = _round_label(match)
        round_settlements[label][s.user_id].append(s)
        if label not in round_kickoff or match.kickoff_time > round_kickoff[label]:
            round_kickoff[label] = match.kickoff_time

    round_standings = []
    for label in sorted(round_kickoff, key=lambda r: round_kickoff[r], reverse=True):
        user_stats = sorted(
            [
                {"user": u, **_stats(round_settlements[label].get(u.id, []), multiplier_by_user.get(u.id, Decimal("1")))}
                for u in members
                if round_settlements[label].get(u.id)  # only show eligible members
            ],
            key=lambda x: (x["correct"], x["net"]),
            reverse=True,
        )
        round_standings.append({"label": label, "members": user_stats})

    # Load existing wagers for this group (for owner UI)
    wagers_result = await db.execute(
        select(GroupWager).where(GroupWager.group_id == group_id)
    )
    wagers_by_round: dict[str, GroupWager] = {
        w.round_name: w for w in wagers_result.scalars().all()
    }

    return templates.TemplateResponse(
        "scoreboard/group.html",
        {
            "request": request,
            "current_user": current_user,
            "group": group,
            "all_groups": all_groups,
            "standings": standings,
            "round_standings": round_standings,
            "match_rows": match_rows,
            "members": members,
            "multiplier_by_user": multiplier_by_user,
            "tournament_rounds": TOURNAMENT_ROUNDS,
            "wagers_by_round": wagers_by_round,
        },
    )
