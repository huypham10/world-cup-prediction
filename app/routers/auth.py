from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from ..auth import service as auth_svc
from ..auth.dependencies import get_current_user
from ..auth.session import make_session_cookie
from ..database import get_db
from ..limiter import limiter
from ..models.user import User
from ..templates import templates
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

_COOKIE = "session"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 60  # 60 days


def _login_response(destination: str, user_id: int) -> RedirectResponse:
    resp = RedirectResponse(destination, status_code=302)
    resp.set_cookie(
        key=_COOKIE,
        value=make_session_cookie(user_id),
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return resp


@router.get("/register")
async def register_page(
    request: Request, current_user: Optional[User] = Depends(get_current_user)
):
    if current_user:
        return RedirectResponse("/matches", status_code=302)
    return templates.TemplateResponse(
        "auth/register.html", {"request": request, "current_user": None}
    )


@router.post("/register")
@limiter.limit("20/hour")
async def register(
    request: Request,
    name: str = Form(...),
    pin: str = Form(...),
    pin_confirm: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if current_user:
        return RedirectResponse("/matches", status_code=302)

    errors = []
    if not name.strip():
        errors.append("Name is required")
    if len(pin) != 6 or not pin.isdigit():
        errors.append("PIN must be exactly 6 digits")
    elif pin != pin_confirm:
        errors.append("PINs do not match")

    if not errors:
        user, err = await auth_svc.register(db, name.strip(), pin)
        if err:
            errors.append(err)
        else:
            return _login_response("/matches", user.id)

    return templates.TemplateResponse(
        "auth/register.html",
        {"request": request, "current_user": None, "errors": errors, "name": name},
        status_code=422,
    )


@router.get("/login")
async def login_page(
    request: Request, current_user: Optional[User] = Depends(get_current_user)
):
    if current_user:
        return RedirectResponse("/matches", status_code=302)
    return templates.TemplateResponse(
        "auth/login.html", {"request": request, "current_user": None}
    )


@router.post("/login")
@limiter.limit("20/hour")
async def login(
    request: Request,
    name: str = Form(...),
    pin: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if current_user:
        return RedirectResponse("/matches", status_code=302)

    user, error, needs_reset = await auth_svc.attempt_login(db, name.strip(), pin)

    if needs_reset:
        # pin_hash is None — redirect to set-pin flow
        return RedirectResponse(f"/set-pin?name={name.strip()}", status_code=302)

    if error:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "current_user": None, "error": error, "name": name},
            status_code=422,
        )

    return _login_response("/matches", user.id)


@router.get("/set-pin")
async def set_pin_page(request: Request, name: str = ""):
    if not name:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        "auth/set_pin.html", {"request": request, "current_user": None, "name": name}
    )


@router.post("/set-pin")
async def set_pin(
    request: Request,
    name: str = Form(...),
    pin: str = Form(...),
    pin_confirm: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    errors = []
    if len(pin) != 6 or not pin.isdigit():
        errors.append("PIN must be exactly 6 digits")
    elif pin != pin_confirm:
        errors.append("PINs do not match")

    if not errors:
        user, err = await auth_svc.set_new_pin(db, name.strip(), pin)
        if err:
            errors.append(err)
        else:
            return _login_response("/matches", user.id)

    return templates.TemplateResponse(
        "auth/set_pin.html",
        {"request": request, "current_user": None, "errors": errors, "name": name},
        status_code=422,
    )


@router.post("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(_COOKIE)
    return resp
