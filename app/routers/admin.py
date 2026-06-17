from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import service as auth_svc
from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.site_config import SiteConfig
from ..models.user import User
from ..templates import templates

router = APIRouter()


def _require_admin(current_user: Optional[User]) -> bool:
    """User with id=1 is the app admin (the creator)."""
    return current_user is not None and current_user.id == 1


async def get_site_config(db: AsyncSession) -> SiteConfig:
    result = await db.execute(select(SiteConfig).where(SiteConfig.id == 1))
    config = result.scalar_one_or_none()
    if config is None:
        config = SiteConfig(id=1, show_odds=True)
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return config


@router.get("/admin")
async def admin_panel(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _require_admin(current_user):
        return RedirectResponse("/matches" if current_user else "/login", status_code=302)
    result = await db.execute(select(User).order_by(User.id))
    users = result.scalars().all()
    config = await get_site_config(db)
    return templates.TemplateResponse(
        "admin/users.html",
        {"request": request, "current_user": current_user, "users": users, "show_odds": config.show_odds},
    )


@router.post("/admin/toggle-odds")
async def toggle_odds(
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _require_admin(current_user):
        return RedirectResponse("/matches" if current_user else "/login", status_code=302)
    config = await get_site_config(db)
    config.show_odds = not config.show_odds
    await db.commit()
    return RedirectResponse("/admin", status_code=302)


@router.post("/admin/users/{user_id}/reset-pin")
async def admin_reset_pin(
    user_id: int,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _require_admin(current_user):
        return RedirectResponse("/matches" if current_user else "/login", status_code=302)
    await auth_svc.admin_reset_pin(db, user_id)
    return RedirectResponse("/admin", status_code=302)
