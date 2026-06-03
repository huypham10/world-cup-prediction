import secrets
import string
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_current_user
from ..database import get_db, AsyncSessionLocal
from ..models.group import Group
from ..models.group_wager import GroupWager, TOURNAMENT_ROUNDS
from ..models.match import Match
from ..models.membership import Membership
from ..models.settlement import Settlement
from ..models.user import User
from ..tasks.poll_and_settle import settle
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
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user:
        return RedirectResponse("/login", status_code=302)

    if not name.strip():
        return templates.TemplateResponse(
            "groups/create.html",
            {"request": request, "current_user": current_user,
             "errors": ["Group name is required"], "name": name},
            status_code=422,
        )

    join_code = await _unique_join_code(db)
    group = Group(name=name.strip(), owner_id=current_user.id, join_code=join_code)
    db.add(group)
    await db.flush()
    db.add(Membership(group_id=group.id, user_id=current_user.id, role="owner"))
    await db.commit()
    return RedirectResponse(f"/groups/{group.id}/scoreboard", status_code=302)


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


@router.post("/groups/{group_id}/wagers")
async def update_wagers(
    group_id: int,
    round_name: list[str] = Form(...),
    win_amount: list[str] = Form(...),
    loss_amount: list[str] = Form(...),
    late_join_counts_as_loss: Optional[str] = Form(None),
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user:
        return RedirectResponse("/login", status_code=302)

    result = await db.execute(
        select(Group).where(Group.id == group_id, Group.owner_id == current_user.id)
    )
    group = result.scalar_one_or_none()
    if not group:
        return RedirectResponse("/groups", status_code=302)

    group.late_join_counts_as_loss = late_join_counts_as_loss == "1"

    for r, w_raw, l_raw in zip(round_name, win_amount, loss_amount):
        if r not in TOURNAMENT_ROUNDS:
            continue
        try:
            w = Decimal(w_raw.strip()) if w_raw.strip() else None
            l = Decimal(l_raw.strip()) if l_raw.strip() else None
            if w is not None and w <= 0:
                w = None
            if l is not None and l <= 0:
                l = None
        except InvalidOperation:
            continue

        stmt = (
            pg_insert(GroupWager)
            .values(group_id=group_id, round_name=r, win_amount=w, loss_amount=l)
            .on_conflict_do_update(
                index_elements=["group_id", "round_name"],
                set_={"win_amount": w, "loss_amount": l},
            )
        )
        await db.execute(stmt)

    await db.commit()
    return RedirectResponse(f"/groups/{group_id}/scoreboard", status_code=302)


@router.post("/groups/{group_id}/resettle")
async def resettle(
    group_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user:
        return RedirectResponse("/login", status_code=302)

    result = await db.execute(
        select(Group).where(Group.id == group_id, Group.owner_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        return RedirectResponse("/groups", status_code=302)

    await db.execute(delete(Settlement).where(Settlement.group_id == group_id))
    await db.execute(
        update(Match)
        .where(Match.status == "finished", Match.result.is_not(None))
        .values(settled=False)
    )
    await db.commit()

    # Fresh session — bulk UPDATE leaves stale objects in the request session's
    # identity map, so settle() would see 0 unsettled matches on the same session.
    async with AsyncSessionLocal() as fresh_db:
        await settle(fresh_db)

    return RedirectResponse(f"/groups/{group_id}/scoreboard", status_code=302)


@router.post("/groups/{group_id}/members/{user_id}/remove")
async def remove_member(
    group_id: int,
    user_id: int,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user:
        return RedirectResponse("/login", status_code=302)

    # Only the group owner can remove members
    result = await db.execute(
        select(Group).where(Group.id == group_id, Group.owner_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        return RedirectResponse(f"/groups/{group_id}/scoreboard", status_code=302)

    # Can't remove yourself (owner)
    if user_id == current_user.id:
        return RedirectResponse(f"/groups/{group_id}/scoreboard", status_code=302)

    await db.execute(
        delete(Membership).where(
            Membership.group_id == group_id,
            Membership.user_id == user_id,
        )
    )
    await db.commit()
    return RedirectResponse(f"/groups/{group_id}/scoreboard", status_code=302)
