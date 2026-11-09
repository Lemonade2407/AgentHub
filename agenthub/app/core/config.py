"""运行期配置。数据库设计文档 §7.3。归属：D（Platform Backend）。

所有配置均可通过环境变量或 `.env` 覆盖，例如：

    DATABASE_URL=postgresql+asyncpg://agenthub:agenthub@localhost:5432/agenthub
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://agenthub:agenthub@localhost:5432/agenthub"

    db_echo: bool = False
    sql_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # 本地开发自动建表；生产环境应改用 Alembic 迁移
    auto_create_schema: bool = True
    # 是否允许注册/localhost 与私网地址的 MCP Server（本地联调 Demo 时置 true）
    allow_private_mcp: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
