from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from ..config import settings

_serializer = URLSafeTimedSerializer(settings.SESSION_SECRET, salt="session")
_MAX_AGE = 60 * 60 * 24 * 60  # 60 days


def make_session_cookie(user_id: int) -> str:
    return _serializer.dumps({"user_id": user_id})


def read_session_cookie(token: str) -> int | None:
    try:
        data = _serializer.loads(token, max_age=_MAX_AGE)
        return int(data["user_id"])
    except (BadSignature, SignatureExpired, KeyError, ValueError):
        return None
