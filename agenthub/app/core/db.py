"""异步数据库引擎与会话工厂（数据库设计文档 §7.3）。

约定：
- 引擎默认语句超时 15s；Trace 写入场景需在 session 内 `SET LOCAL statement_timeout='3s'`。
- 所有 DB 访问经 `app/repositories/`，API / Runtime 层不直接持有 AsyncSession（§7.5）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={
            "server_settings": {
                "statement_timeout": "15000",
                "idle_in_transaction_session_timeout": "30000",
                "application_name": "agenthub",
            }
        },
    )


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：`Depends(get_session)`。"""
    async with get_session_factory()() as session:
        yield session
