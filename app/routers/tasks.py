"""
HTTP endpoint for the poll-and-settle task.
Called by GitHub Actions every 20 minutes.
The POST request wakes the web app if it is sleeping (Neon scale-to-zero / idle host).
"""
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from ..config import settings
from ..tasks.poll_and_settle import run as poll_run

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
