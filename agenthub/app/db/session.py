"""异步数据库会话。数据库设计文档 §7.1。归属：D（Platform Backend）。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db import models  # noqa: F401  确保模型注册到 metadata
from app.db.models import Base

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.sql_echo,
    pool_pre_ping=True,
)

SessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session


async def create_schema() -> None:
    """本地开发建表；生产环境应改用 Alembic 迁移。

    V1 与 V2 各有独立的 `Base`（历史原因），这里按顺序建表：
    V1 先建既有六表，V2 的 `create_all(checkfirst=True)` 会跳过已存在的表，
    只补齐 `app_user / model_api / skill / agent_skill` 等 V2 新表。
    """
    from app.models import Base as V2Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(V2Base.metadata.create_all)
        # V1 的 Agent 模型不含 V2 字段；自动建表时补齐列，供模型凭据解析 /
        # Agent Center 安装写入使用（Alembic 建库环境由 0002 迁移完成）。
        if engine.dialect.name == "postgresql":
            for ddl in (
                "ALTER TABLE agent ADD COLUMN IF NOT EXISTS owner_id bigint",
                "ALTER TABLE agent ADD COLUMN IF NOT EXISTS model_api_id bigint",
                "ALTER TABLE agent ADD COLUMN IF NOT EXISTS model_key varchar(128)",
            ):
                await conn.execute(text(ddl))
