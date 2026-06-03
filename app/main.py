from contextlib import asynccontextmanager
from typing import Optional
import logging

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from .limiter import limiter

from .auth.dependencies import get_current_user
from .database import AsyncSessionLocal, engine
from .config import settings
from .models.user import User
from .routers import auth as auth_router
from .routers import groups as groups_router
from .routers import admin as admin_router
from .routers import matches as matches_router
from .routers import scoreboard as scoreboard_router
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
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Paths that don't require a session cookie
_PUBLIC = {"/login", "/register", "/set-pin", "/logout", "/health", "/tasks/poll"}

@app.middleware("http")
async def require_session(request: Request, call_next):
    if request.url.path not in _PUBLIC and not request.cookies.get("session"):
        return RedirectResponse("/login", status_code=302)
    return await call_next(request)


app.include_router(auth_router.router)
app.include_router(groups_router.router)
app.include_router(admin_router.router)
app.include_router(matches_router.router)
app.include_router(scoreboard_router.router)
app.include_router(tasks_router.router)


@app.get("/")
async def home(current_user: Optional[User] = Depends(get_current_user)):
    if current_user:
        return RedirectResponse("/groups", status_code=302)
    return RedirectResponse("/login", status_code=302)


@app.get("/health")
async def health():
    return {"status": "ok"}
