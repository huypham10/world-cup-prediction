"""
HTTP endpoint for the poll-and-settle task.
Called by GitHub Actions every 20 minutes.
The POST request wakes the web app if it is sleeping (Neon scale-to-zero / idle host).
"""
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from ..config import settings
from ..tasks.poll_and_settle import run as poll_run, run_odds as odds_run, run_settle as settle_run, sync as sync_run

router = APIRouter()


@router.post("/tasks/poll", status_code=202)
async def trigger_poll(
    background_tasks: BackgroundTasks,
    x_task_secret: str = Header(..., alias="X-Task-Secret"),
):
    """
    Trigger poll-and-settle in the background.
    Returns 202 immediately; the task runs asynchronously.
    Guard: X-Task-Secret header must match TASK_SECRET env var.
    """
    if x_task_secret != settings.TASK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid task secret")
    background_tasks.add_task(poll_run)
    return {"status": "accepted"}


@router.post("/tasks/sync", status_code=202)
async def trigger_sync(
    background_tasks: BackgroundTasks,
    x_task_secret: str = Header(..., alias="X-Task-Secret"),
    force: bool = False,
):
    """Fetch and upsert fixtures from the football API only. No settlement.
    Pass ?force=true to bypass the active-match check."""
    if x_task_secret != settings.TASK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid task secret")
    background_tasks.add_task(sync_run, force)
    return {"status": "accepted"}


@router.post("/tasks/settle", status_code=202)
async def trigger_settle(
    background_tasks: BackgroundTasks,
    x_task_secret: str = Header(..., alias="X-Task-Secret"),
):
    """Settle finished, unsettled matches only. No fixture sync."""
    if x_task_secret != settings.TASK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid task secret")
    background_tasks.add_task(settle_run)
    return {"status": "accepted"}


@router.post("/tasks/odds", status_code=202)
async def trigger_odds(
    background_tasks: BackgroundTasks,
    x_task_secret: str = Header(..., alias="X-Task-Secret"),
):
    """Fetch bookmaker odds for upcoming scheduled matches only."""
    if x_task_secret != settings.TASK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid task secret")
    background_tasks.add_task(odds_run)
    return {"status": "accepted"}
