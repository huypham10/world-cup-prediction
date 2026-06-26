from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..config import settings
from ..database import get_db
from ..football_client.client import BzzOiroClient
from ..football_client.sync import is_knockout_match, sync_fixtures
from ..models.match import Match
from ..models.prediction import Prediction
from ..models.user import User
from ..templates import templates
from .admin import get_site_config

router = APIRouter()


def _get_client() -> BzzOiroClient:
    return BzzOiroClient(
        api_key=settings.FOOTBALL_API_KEY,
        base_url=settings.FOOTBALL_API_BASE_URL,
        league_id=settings.FOOTBALL_LEAGUE_ID,
    )


@router.get("/matches")
async def matches_list(
    request: Request,
    synced: Optional[int] = None,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user:
        return RedirectResponse("/login", status_code=302)

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Match)
        .where(
            Match.league_id == settings.FOOTBALL_LEAGUE_ID,
            Match.kickoff_time >= now - timedelta(hours=24),
            Match.kickoff_time <= now + timedelta(days=14),
        )
        .order_by(Match.kickoff_time)
    )
    matches = result.scalars().all()

    predictions: dict[int, Prediction] = {}
    if matches:
        pred_result = await db.execute(
            select(Prediction).where(
                Prediction.user_id == current_user.id,
                Prediction.match_id.in_([m.id for m in matches]),
            )
        )
        predictions = {p.match_id: p for p in pred_result.scalars().all()}

    match_data = [
        {
            "match": m,
            "prediction": predictions.get(m.id),
            "locked": m.kickoff_time <= now or m.status == "finished" or m.status.startswith("live"),
            "is_knockout": is_knockout_match(m),
        }
        for m in matches
    ]

    config = await get_site_config(db)

    return templates.TemplateResponse(
        "matches/list.html",
        {
            "request": request,
            "current_user": current_user,
            "matches": match_data,
            "now": now,
            "synced": synced,
            "show_odds": config.show_odds,
        },
    )


@router.post("/matches/sync")
async def sync_matches(
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger a fixture fetch from the football API. Redirects back to /matches."""
    if not current_user:
        return RedirectResponse("/login", status_code=302)
    count, _ = await sync_fixtures(db, _get_client(), settings.round_date_rules or None)
    return RedirectResponse(f"/matches?synced={count}", status_code=302)


@router.post("/matches/{match_id}/predict")
async def submit_prediction(
    request: Request,
    match_id: int,
    pick: Optional[str] = Form(None),
    final_pick: Optional[str] = Form(None),
    odds_visible: Optional[str] = Form(None),
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user:
        return RedirectResponse("/login", status_code=302)

    if pick is not None and pick not in ("A", "B", "draw"):
        raise HTTPException(status_code=422, detail="Invalid pick value")
    if final_pick is not None and final_pick not in ("A", "B"):
        raise HTTPException(status_code=422, detail="Invalid final_pick value")

    match = await db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    now = datetime.now(timezone.utc)
    locked = match.kickoff_time <= now or match.status in ("live", "finished")
    if locked:
        raise HTTPException(status_code=409, detail="Predictions are locked after kickoff")

    knockout = is_knockout_match(match)

    # Consistency rule: if pick is A or B (outright win), final winner is the same team automatically.
    # Only a draw in 90 min leads to ET/PK where the user chooses the final winner.
    if not knockout:
        final_pick = None
    elif pick in ("A", "B"):
        final_pick = pick  # auto-set; no ET/PK possible if one team wins outright
    # if pick == "draw" or pick is None: keep user-submitted final_pick as-is

    # Upsert prediction
    result = await db.execute(
        select(Prediction).where(
            Prediction.user_id == current_user.id,
            Prediction.match_id == match_id,
        )
    )
    pred = result.scalar_one_or_none()
    ov = (odds_visible == "true") if odds_visible is not None else None

    if pick is None:
        # Final-pick-only update — existing prediction required
        if not pred:
            raise HTTPException(status_code=422, detail="Place a 90-min pick first")
        if final_pick is not None:
            pred.final_pick = final_pick
    elif pred:
        pred.pick = pick
        pred.final_pick = final_pick
        if ov is not None:
            pred.odds_visible = ov
    else:
        pred = Prediction(
            user_id=current_user.id,
            match_id=match_id,
            pick=pick,
            final_pick=final_pick,
            odds_visible=ov,
        )
        db.add(pred)
    await db.commit()
    await db.refresh(pred)

    config = await get_site_config(db)

    # HTMX requests get a partial HTML response; plain form submits get a redirect
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        return templates.TemplateResponse(
            "matches/_prediction_widget.html",
            {
                "request": request,
                "match": match,
                "prediction": pred,
                "locked": False,
                "show_odds": config.show_odds,
                "is_knockout": knockout,
            },
        )
    return RedirectResponse("/matches", status_code=302)
