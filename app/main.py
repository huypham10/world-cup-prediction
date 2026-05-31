from contextlib import asynccontextmanager
from typing import Optional
import logging

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import text

from .auth.dependencies import get_current_user
from .database import AsyncSessionLocal, engine
from .config import settings
from .models.user import User
from .routers import auth as auth_router
from .routers import groups as groups_router
from .routers import admin as admin_router
from .routers import matches as matches_router
from .routers import tasks as tasks_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))
    logger.info("DB connection OK")
    yield
    await engine.dispose()


app = FastAPI(
    title="World Cup Prediction Pool",
    lifespan=lifespan,
    debug=settings.DEBUG,
)

app.include_router(auth_router.router)
app.include_router(groups_router.router)
app.include_router(admin_router.router)
app.include_router(matches_router.router)
app.include_router(tasks_router.router)


@app.get("/")
async def home(current_user: Optional[User] = Depends(get_current_user)):
    if current_user:
        return RedirectResponse("/groups", status_code=302)
    return RedirectResponse("/login", status_code=302)


@app.get("/health")
async def health():
    return {"status": "ok"}
