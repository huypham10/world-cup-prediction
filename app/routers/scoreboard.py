from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..config import settings
from ..database import get_db
from ..football_client.sync import is_knockout_match
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

        # Index settlements by (match_id, user_id, prediction_type) for match history
        by_match_user_type: dict[tuple[int, int, str], Settlement] = {
            (s.match_id, s.user_id, s.prediction_type): s for s in all_settlements
        }

        for match in settled_matches:
            knockout = is_knockout_match(match)
            member_results = []
            for user in members:
                s90 = by_match_user_type.get((match.id, user.id, "90min"))
                sf = by_match_user_type.get((match.id, user.id, "final"))
                p = preds_by_match_user.get((match.id, user.id))
                if s90 is None:
                    member_results.append({
                        "user": user, "pick": None, "final_pick": None,
                        "correct": None, "amount": None,
                        "final_correct": None, "final_amount": None,
                        "eligible": False,
                    })
                else:
                    member_results.append({
                        "user": user,
                        "pick": p.pick if p else None,
                        "final_pick": p.final_pick if p else None,
                        "correct": s90.correct,
                        "amount": s90.amount,
                        "final_correct": sf.correct if sf else None,
                        "final_amount": sf.amount if sf else None,
                        "eligible": True,
                    })
            match_rows.append({"match": match, "member_results": member_results, "is_knockout": knockout})

    # Overall standings — aggregate across all settlements per user
    by_user: dict[int, list[Settlement]] = {u.id: [] for u in members}
    for s in all_settlements:
        by_user.setdefault(s.user_id, []).append(s)

    # Which match_ids each user actually submitted a prediction for (excludes auto-losses)
    predicted_match_ids_by_user: dict[int, set[int]] = defaultdict(set)
    for (match_id, user_id) in preds_by_match_user:
        predicted_match_ids_by_user[user_id].add(match_id)

    def _weight(s: Settlement) -> float:
        """Knockout matches produce two settlement rows (90min + final), each worth 0.5."""
        if s.prediction_type == "final":
            return 0.5
        match = matches_by_id.get(s.match_id)
        return 0.5 if (match and is_knockout_match(match)) else 1.0

    def _stats(settlements: list[Settlement], multiplier: Decimal = Decimal("1"), predicted_match_ids: set[int] | None = None) -> dict:
        predicted_match_ids = predicted_match_ids or set()
        played = sum(_weight(s) for s in settlements)
        correct = sum(_weight(s) for s in settlements if s.correct)
        wrong = sum(_weight(s) for s in settlements if not s.correct and s.match_id in predicted_match_ids)
        predicted = correct + wrong
        no_pred = played - predicted
        miss_pct = round(wrong / predicted * 100) if predicted else 0
        raw_net = sum((s.amount for s in settlements if s.amount is not None), Decimal(0))
        net = (raw_net * multiplier).quantize(Decimal("0.01"))
        win_pct = round(correct / played * 100) if played else 0
        return {"correct": correct, "wrong": wrong, "no_pred": no_pred, "played": played, "net": net, "win_pct": win_pct, "miss_pct": miss_pct}

    def _knockout_round_stats(settlements: list[Settlement], multiplier: Decimal = Decimal("1"), predicted_match_ids: set[int] | None = None) -> dict:
        predicted_match_ids = predicted_match_ids or set()
        s90 = [s for s in settlements if s.prediction_type == "90min"]
        sft = [s for s in settlements if s.prediction_type == "final"]
        p = len(s90)

        correct_90 = sum(1 for s in s90 if s.correct)
        wrong_90 = sum(1 for s in s90 if not s.correct and s.match_id in predicted_match_ids)
        null_90 = p - correct_90 - wrong_90
        predicted_90 = correct_90 + wrong_90
        win_pct_90 = round(correct_90 / p * 100) if p else 0
        miss_pct_90 = round(wrong_90 / predicted_90 * 100) if predicted_90 else 0

        correct_ft = sum(1 for s in sft if s.correct)
        wrong_ft = sum(1 for s in sft if not s.correct and s.match_id in predicted_match_ids)
        null_ft = len(sft) - correct_ft - wrong_ft
        predicted_ft = correct_ft + wrong_ft
        win_pct_ft = round(correct_ft / len(sft) * 100) if sft else 0
        miss_pct_ft = round(wrong_ft / predicted_ft * 100) if predicted_ft else 0

        raw_net = sum((s.amount for s in settlements if s.amount is not None), Decimal(0))
        net = (raw_net * multiplier).quantize(Decimal("0.01"))
        return {
            "played": p,
            "correct_90": correct_90, "wrong_90": wrong_90, "win_pct_90": win_pct_90, "miss_pct_90": miss_pct_90, "null_90": null_90,
            "correct_ft": correct_ft, "wrong_ft": wrong_ft, "win_pct_ft": win_pct_ft, "miss_pct_ft": miss_pct_ft, "null_ft": null_ft,
            "net": net,
            "correct": correct_90,  # for sort compat
        }

    standings = sorted(
        [{"user": u, **_stats(by_user.get(u.id, []), multiplier_by_user.get(u.id, Decimal("1")), predicted_match_ids_by_user.get(u.id))} for u in members],
        key=lambda x: (x["win_pct"], x["played"], x["net"]),
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
        all_round_setts = [s for setts in round_settlements[label].values() for s in setts]
        round_is_knockout = any(s.prediction_type == "final" for s in all_round_setts)
        stats_fn = _knockout_round_stats if round_is_knockout else _stats
        user_stats = sorted(
            [
                {"user": u, **stats_fn(round_settlements[label].get(u.id, []), multiplier_by_user.get(u.id, Decimal("1")), predicted_match_ids_by_user.get(u.id))}
                for u in members
                if round_settlements[label].get(u.id)  # only show eligible members
            ],
            key=lambda x: (x["correct_90"], x["correct_ft"]) if round_is_knockout else (x["correct"], x["net"]),
            reverse=True,
        )
        round_standings.append({"label": label, "members": user_stats, "is_knockout": round_is_knockout})

    # Load existing wagers for this group (for owner UI)
    wagers_result = await db.execute(
        select(GroupWager).where(GroupWager.group_id == group_id)
    )
    wagers_by_round: dict[str, GroupWager] = {
        w.round_name: w for w in wagers_result.scalars().all()
    }

    # Upcoming matches within 24h that still accept predictions
    now = datetime.now(timezone.utc)
    upcoming_result = await db.execute(
        select(Match)
        .where(
            Match.league_id == settings.FOOTBALL_LEAGUE_ID,
            Match.status == "scheduled",
            Match.kickoff_time > now,
            Match.kickoff_time <= now + timedelta(hours=24),
        )
        .order_by(Match.kickoff_time)
    )
    upcoming_matches = upcoming_result.scalars().all()

    non_voters_by_match: list[dict] = []
    if upcoming_matches and member_ids:
        upcoming_ids = [m.id for m in upcoming_matches]
        voted_result = await db.execute(
            select(Prediction.match_id, Prediction.user_id, Prediction.final_pick).where(
                Prediction.match_id.in_(upcoming_ids),
                Prediction.user_id.in_(member_ids),
            )
        )
        # Map (match_id, user_id) → final_pick (None if not predicted or no final pick)
        upcoming_preds: dict[tuple[int, int], str | None] = {
            (r.match_id, r.user_id): r.final_pick for r in voted_result
        }
        for match in upcoming_matches:
            knockout = is_knockout_match(match)
            missing = []
            for u in members:
                pred = upcoming_preds.get((match.id, u.id))
                if pred is None and (match.id, u.id) not in upcoming_preds:
                    missing.append(u)  # no prediction at all
                elif knockout and upcoming_preds.get((match.id, u.id)) is None and (match.id, u.id) in upcoming_preds:
                    missing.append(u)  # has 90-min pick but no final_pick
            non_voters_by_match.append({"match": match, "non_voters": missing, "is_knockout": knockout})

    # Live matches — show predictions without outcome
    live_match_rows = []
    if member_ids:
        live_result = await db.execute(
            select(Match)
            .where(
                Match.league_id == settings.FOOTBALL_LEAGUE_ID,
                Match.status.like("live%"),
            )
            .order_by(Match.kickoff_time.desc())
        )
        live_matches = live_result.scalars().all()
        if live_matches:
            live_ids = [m.id for m in live_matches]
            live_preds_result = await db.execute(
                select(Prediction).where(
                    Prediction.match_id.in_(live_ids),
                    Prediction.user_id.in_(member_ids),
                )
            )
            live_preds = {
                (p.match_id, p.user_id): p for p in live_preds_result.scalars().all()
            }
            for match in live_matches:
                knockout = is_knockout_match(match)
                live_match_rows.append({
                    "match": match,
                    "is_knockout": knockout,
                    "member_results": [
                        {
                            "user": u,
                            "pick": live_preds[(match.id, u.id)].pick if (match.id, u.id) in live_preds else None,
                            "final_pick": live_preds[(match.id, u.id)].final_pick if (match.id, u.id) in live_preds else None,
                        }
                        for u in members
                    ],
                })

    pool_total = sum(s["net"] for s in standings).quantize(Decimal("0.01"))

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
            "non_voters_by_match": non_voters_by_match,
            "pool_total": pool_total,
            "live_match_rows": live_match_rows,
        },
    )
