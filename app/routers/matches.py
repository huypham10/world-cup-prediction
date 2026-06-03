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
from ..football_client.sync import sync_fixtures
from ..models.match import Match
from ..models.prediction import Prediction
from ..models.user import User
from ..templates import templates

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
            "locked": m.kickoff_time <= now or m.status in ("live", "finished"),
        }
        for m in matches
    ]

    return templates.TemplateResponse(
        "matches/list.html",
        {
            "request": request,
            "current_user": current_user,
            "matches": match_data,
            "now": now,
            "synced": synced,
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
    count = await sync_fixtures(db, _get_client(), settings.ROUND_DATE_RULES or None)
    return RedirectResponse(f"/matches?synced={count}", status_code=302)


@router.post("/matches/{match_id}/predict")
async def submit_prediction(
    request: Request,
    match_id: int,
    pick: str = Form(...),
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user:
        return RedirectResponse("/login", status_code=302)

    if pick not in ("A", "B", "draw"):
        raise HTTPException(status_code=422, detail="Invalid pick value")

    match = await db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    now = datetime.now(timezone.utc)
    locked = match.kickoff_time <= now or match.status in ("live", "finished")
    if locked:
        raise HTTPException(status_code=409, detail="Predictions are locked after kickoff")

    # Upsert prediction
    result = await db.execute(
        select(Prediction).where(
            Prediction.user_id == current_user.id,
            Prediction.match_id == match_id,
        )
    )
    pred = result.scalar_one_or_none()
    if pred:
        pred.pick = pick
    else:
        pred = Prediction(user_id=current_user.id, match_id=match_id, pick=pick)
        db.add(pred)
    await db.commit()
    await db.refresh(pred)

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
            },
        )
    return RedirectResponse("/matches", status_code=302)
