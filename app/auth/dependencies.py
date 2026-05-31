from typing import Optional
from fastapi import Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..models.user import User
from .session import read_session_cookie


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Returns the logged-in User or None. Routes redirect to /login when None."""
    token = request.cookies.get("session")
    if not token:
        return None
    user_id = read_session_cookie(token)
    if not user_id:
        return None
    return await db.get(User, user_id)
