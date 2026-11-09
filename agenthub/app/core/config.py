"""运行期配置（数据库设计文档 §7.3）。

所有配置均可通过环境变量或 `.env` 覆盖，例如：

    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/agenthub
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

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/agenthub"

    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
