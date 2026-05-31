import secrets
import string
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models.group import Group
from ..models.membership import Membership
from ..models.user import User
from ..templates import templates

router = APIRouter()

_CODE_CHARS = string.ascii_uppercase + string.digits
_CODE_LEN = 8


async def _unique_join_code(db: AsyncSession) -> str:
    for _ in range(10):
        code = "".join(secrets.choice(_CODE_CHARS) for _ in range(_CODE_LEN))
        result = await db.execute(select(Group).where(Group.join_code == code))
        if not result.scalar_one_or_none():
            return code
    raise RuntimeError("Could not generate unique join code after 10 attempts")


@router.get("/groups")
async def groups_list(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user:
        return RedirectResponse("/login", status_code=302)
    result = await db.execute(
        select(Group)
        .join(Membership, Membership.group_id == Group.id)
        .where(Membership.user_id == current_user.id)
        .order_by(Group.name)
    )
    groups = result.scalars().all()
    return templates.TemplateResponse(
        "groups/list.html",
        {"request": request, "current_user": current_user, "groups": groups},
    )


@router.get("/groups/new")
async def create_group_page(
    request: Request, current_user: Optional[User] = Depends(get_current_user)
):
    if not current_user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        "groups/create.html", {"request": request, "current_user": current_user}
    )


@router.post("/groups/new")
async def create_group(
    request: Request,
    name: str = Form(...),
    stake: str = Form(""),
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user:
        return RedirectResponse("/login", status_code=302)

    errors = []
    stake_val: Optional[Decimal] = None
    if not name.strip():
        errors.append("Group name is required")
    if stake.strip():
        try:
            stake_val = Decimal(stake.strip())
            if stake_val <= 0:
                errors.append("Stake must be greater than zero")
        except InvalidOperation:
            errors.append("Stake must be a number (e.g. 5 or 2.50)")

    if errors:
        return templates.TemplateResponse(
            "groups/create.html",
            {
                "request": request,
                "current_user": current_user,
                "errors": errors,
                "name": name,
                "stake": stake,
            },
            status_code=422,
        )

    join_code = await _unique_join_code(db)
    group = Group(
        name=name.strip(), owner_id=current_user.id, join_code=join_code, stake=stake_val
    )
    db.add(group)
    await db.flush()
    db.add(Membership(group_id=group.id, user_id=current_user.id, role="owner"))
    await db.commit()
    return RedirectResponse("/groups", status_code=302)


@router.get("/groups/join")
async def join_group_page(
    request: Request, current_user: Optional[User] = Depends(get_current_user)
):
    if not current_user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        "groups/join.html", {"request": request, "current_user": current_user}
    )


@router.post("/groups/join")
async def join_group(
    request: Request,
    join_code: str = Form(...),
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user:
        return RedirectResponse("/login", status_code=302)

    code = join_code.strip().upper()
    result = await db.execute(select(Group).where(Group.join_code == code))
    group = result.scalar_one_or_none()

    if not group:
        return templates.TemplateResponse(
            "groups/join.html",
            {
                "request": request,
                "current_user": current_user,
                "error": "Invalid join code",
                "join_code": join_code,
            },
            status_code=422,
        )

    existing = await db.execute(
        select(Membership).where(
            Membership.group_id == group.id, Membership.user_id == current_user.id
        )
    )
    if existing.scalar_one_or_none():
        return templates.TemplateResponse(
            "groups/join.html",
            {
                "request": request,
                "current_user": current_user,
                "error": "You are already a member of this group",
                "join_code": join_code,
            },
            status_code=422,
        )

    db.add(Membership(group_id=group.id, user_id=current_user.id, role="member"))
    await db.commit()
    return RedirectResponse("/groups", status_code=302)
