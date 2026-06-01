import re
import ssl as _ssl
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from typing import AsyncGenerator
from .config import settings


def _build_engine():
    url = settings.DATABASE_URL
    connect_args = {}
    # asyncpg doesn't support sslmode= — strip it and pass an SSL context instead
    if "sslmode=require" in url:
        url = re.sub(r"[?&]sslmode=require", "", url).rstrip("?&")
        connect_args["ssl"] = _ssl.create_default_context()
    return create_async_engine(
        url,
        echo=settings.DEBUG,
        connect_args=connect_args,
        pool_pre_ping=True,
    )


engine = _build_engine()
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
