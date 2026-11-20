"""FastAPI 应用入口。归属：D（Platform Backend）。

本地启动（在 agenthub 目录下）：

    uvicorn app.main:app --reload --port 8001

端口与 `frontend/vite.config.ts` 的 `/api` 代理保持一致。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import (
    agent_center,
    agents,
    maintenance,
    mcp,
    model_apis,
    runs,
    skills,
    workspace,
)
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.middleware import install_request_id_middleware
from app.db.session import SessionFactory, create_schema, engine
from app.mcp.client_adapter import HttpMcpClientFactory
from app.services.run_service import RunService
from app.services.trace_service import SSEBroker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.auto_create_schema:
        await create_schema()
    await _ensure_workspaces()
    await _cleanup_old_runs(settings.run_retention_days)

    client_factory = HttpMcpClientFactory()
    broker = SSEBroker()
    app.state.client_factory = client_factory
    app.state.broker = broker
    app.state.run_service = RunService(SessionFactory, broker, client_factory)
    try:
        yield
    finally:
        await client_factory.aclose()
        await engine.dispose()


async def _ensure_workspaces() -> None:
    """为已有 Agent / Skill 补齐实体工作区目录（新对象在创建时即时创建）。"""
    from sqlalchemy import select

    from app.models.agent import Agent as AgentRow
    from app.models.skill import Skill
    from app.services.workspace_service import ensure_agent_dir, ensure_skill_dir

    try:
        async with SessionFactory() as session:
            agent_ids = (
                (
                    await session.execute(
                        select(AgentRow.id).where(AgentRow.deleted_at.is_(None))
                    )
                )
                .scalars()
                .all()
            )
            skill_ids = (await session.execute(select(Skill.id))).scalars().all()
        for agent_id in agent_ids:
            ensure_agent_dir(agent_id)
        for skill_id in skill_ids:
            ensure_skill_dir(skill_id)
        logging.getLogger(__name__).info(
            "workspaces ready: %d agents / %d skills", len(agent_ids), len(skill_ids)
        )
    except Exception:  # 工作区失败不应阻断平台启动
        logging.getLogger(__name__).exception("初始化 Agent/Skill 工作区失败")


async def _cleanup_old_runs(retention_days: int) -> None:
    """启动时按保留天数清理终态 Run；0 表示关闭自动清理。"""
    if retention_days <= 0:
        return
    from app.services.retention_service import cleanup_runs

    try:
        async with SessionFactory() as session:
            matched, deleted = await cleanup_runs(session, retention_days)
        logging.getLogger(__name__).info(
            "run retention: matched=%d deleted=%d (older than %d days)",
            matched,
            deleted,
            retention_days,
        )
    except Exception:  # 清理失败不应阻断平台启动
        logging.getLogger(__name__).exception("清理历史 Run 失败")


app = FastAPI(
    title="AgentHub API",
    version="0.1.0",
    description="MCP Agent 构建、运行与调试平台后端",
    lifespan=lifespan,
)

install_request_id_middleware(app)
register_exception_handlers(app)

app.include_router(agents.router)
app.include_router(mcp.router)
app.include_router(runs.router)
app.include_router(skills.router)
app.include_router(skills.agent_router)
app.include_router(agent_center.router)
app.include_router(agent_center.agent_router)
app.include_router(model_apis.router)
app.include_router(workspace.router)
app.include_router(workspace.skill_router)
app.include_router(maintenance.router)


@app.get("/api/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=True)
