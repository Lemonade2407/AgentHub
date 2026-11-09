"""应用配置。设计文档 §15 / 契约 §4.2.1。

所有配置均通过环境变量或 `.env` 注入，不在代码中硬编码凭据。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str = "postgresql+asyncpg://agenthub:agenthub@localhost:5432/agenthub"
    # 本地开发未接 Alembic 时自动建表；生产环境应关闭并显式执行迁移
    auto_create_schema: bool = True
    sql_echo: bool = False
    # 契约 §4.2.1：默认禁止 localhost / 私网地址，本地联调可放开
    allow_private_mcp: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
