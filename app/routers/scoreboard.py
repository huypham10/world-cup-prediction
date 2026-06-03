from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.group import Group
from ..models.match import Match
from ..models.membership import Membership
from ..models.prediction import Prediction
from ..models.settlement import Settlement
from ..models.user import User
from ..templates import templates

router = APIRouter()


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

    # All members of this group, ordered by name
    members_result = await db.execute(
        select(User, Membership.joined_at)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.group_id == group_id)
        .order_by(User.name)
    )
    members_rows = members_result.all()
    members = [u for u, _ in members_rows]
    member_ids = [u.id for u in members]

    # Load ALL settlements for this group in one query
    all_settlements_result = await db.execute(
        select(Settlement).where(Settlement.group_id == group_id)
    )
    all_settlements = all_settlements_result.scalars().all()

    # Index settlements by (match_id, user_id) and by user_id
    by_user: dict[int, list[Settlement]] = {u.id: [] for u in members}
    by_match_user: dict[tuple[int, int], Settlement] = {}
    settled_match_ids: set[int] = set()
    for s in all_settlements:
        by_user.setdefault(s.user_id, []).append(s)
        by_match_user[(s.match_id, s.user_id)] = s
        settled_match_ids.add(s.match_id)

    # Build standings (sorted by net desc, then correct desc)
    standings = []
    for user in members:
        user_settlements = by_user.get(user.id, [])
        correct = sum(1 for s in user_settlements if s.correct)
        wrong = sum(1 for s in user_settlements if not s.correct)
        net = sum(
            (s.amount for s in user_settlements if s.amount is not None),
            Decimal(0),
        )
        standings.append({
            "user": user,
            "correct": correct,
            "wrong": wrong,
            "played": len(user_settlements),
            "net": net,
        })
    standings.sort(key=lambda x: (x["net"], x["correct"]), reverse=True)

    # Load settled matches + all member predictions in two queries
    match_rows = []
    if settled_match_ids:
        matches_result = await db.execute(
            select(Match)
            .where(Match.id.in_(settled_match_ids))
            .order_by(Match.kickoff_time.desc())
        )
        settled_matches = matches_result.scalars().all()

        preds_result = await db.execute(
            select(Prediction).where(
                Prediction.match_id.in_(settled_match_ids),
                Prediction.user_id.in_(member_ids),
            )
        )
        preds_by_match_user: dict[tuple[int, int], Prediction] = {
            (p.match_id, p.user_id): p for p in preds_result.scalars().all()
        }

        for match in settled_matches:
            member_results = []
            for user in members:
                s = by_match_user.get((match.id, user.id))
                p = preds_by_match_user.get((match.id, user.id))
                if s is None:
                    # Joined after kickoff — not settled
                    member_results.append({
                        "user": user,
                        "pick": None,
                        "correct": None,
                        "amount": None,
                        "eligible": False,
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

    return templates.TemplateResponse(
        "scoreboard/group.html",
        {
            "request": request,
            "current_user": current_user,
            "group": group,
            "all_groups": all_groups,
            "standings": standings,
            "match_rows": match_rows,
            "members": members,
        },
    )
