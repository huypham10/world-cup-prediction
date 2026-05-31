from datetime import datetime, timezone, timedelta
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models.user import User

_crypt = CryptContext(schemes=["bcrypt"], deprecated="auto")

MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def hash_pin(pin: str) -> str:
    return _crypt.hash(pin)


def _verify_pin(pin: str, pin_hash: str) -> bool:
    return _crypt.verify(pin, pin_hash)


async def get_user_by_name(db: AsyncSession, name: str) -> User | None:
    result = await db.execute(select(User).where(User.name == name))
    return result.scalar_one_or_none()


async def register(db: AsyncSession, name: str, pin: str) -> tuple[User | None, str | None]:
    """Create a new user. Returns (user, None) on success or (None, error_message) on failure."""
    existing = await get_user_by_name(db, name)
    if existing:
        return None, "This name is already taken"
    user = User(name=name, pin_hash=hash_pin(pin))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, None


async def attempt_login(
    db: AsyncSession, name: str, pin: str
) -> tuple[User | None, str | None, bool]:
    """
    Try to log in. Returns (user, error_msg, needs_pin_reset).
    - On success: (user, None, False)
    - On locked account: (None, message, False)
    - On PIN reset required: (None, None, True)
    - On bad credentials: (None, message, False)
    """
    user = await get_user_by_name(db, name)
    if not user:
        return None, "Invalid name or PIN", False

    now = datetime.now(timezone.utc)

    if user.locked_until and user.locked_until > now:
        remaining = max(1, int((user.locked_until - now).total_seconds() / 60) + 1)
        return None, f"Too many failed attempts. Try again in {remaining} minute(s).", False

    if user.pin_hash is None:
        # Admin reset the PIN — redirect user to set a new one
        return None, None, True

    if not _verify_pin(pin, user.pin_hash):
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= MAX_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
        await db.commit()
        return None, "Invalid name or PIN", False

    # Success — clear lockout state
    user.failed_attempts = 0
    user.locked_until = None
    await db.commit()
    return user, None, False


async def set_new_pin(
    db: AsyncSession, name: str, new_pin: str
) -> tuple[User | None, str | None]:
    """Set a new PIN for a user whose pin_hash is None (admin-reset state)."""
    user = await get_user_by_name(db, name)
    if not user:
        return None, "User not found"
    if user.pin_hash is not None:
        return None, "PIN reset is not active for this account"
    user.pin_hash = hash_pin(new_pin)
    user.failed_attempts = 0
    user.locked_until = None
    await db.commit()
    return user, None


async def admin_reset_pin(db: AsyncSession, user_id: int) -> bool:
    """Set pin_hash = None so the user must choose a new PIN on next login."""
    user = await db.get(User, user_id)
    if not user:
        return False
    user.pin_hash = None
    user.failed_attempts = 0
    user.locked_until = None
    await db.commit()
    return True
