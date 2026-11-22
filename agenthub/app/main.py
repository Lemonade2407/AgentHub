"""FastAPI 应用入口。归属：D（Platform Backend）。

本地启动（在 agenthub 目录下）：

    uvicorn app.main:app --reload --port 8001

端口与 `frontend/vite.config.ts` 的 `/api` 代理保持一致。
"""

from __future__ import annotations

import asyncio
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
    seed_task = asyncio.create_task(_auto_seed_demo_data())

    client_factory = HttpMcpClientFactory()
    broker = SSEBroker()
    app.state.client_factory = client_factory
    app.state.broker = broker
    app.state.run_service = RunService(SessionFactory, broker, client_factory)
    try:
        yield
    finally:
        seed_task.cancel()
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


async def _auto_seed_demo_data() -> None:
    """首次启动时自动写入内置 Agent / Skill（后台执行，不阻塞启动）。

    仅当数据库中一个内置 Agent 都不存在时才执行，避免覆盖用户后续修改。
    """
    from sqlalchemy import func, select

    from app.db.seed import BUILTIN_AGENT_NAMES, seed_demo_data
    from app.db.session import SessionFactory as _SessionFactory
    from app.models.agent import Agent

    log = logging.getLogger(__name__)
    try:
        async with _SessionFactory() as session:
            existing = (
                await session.execute(
                    select(func.count())
                    .select_from(Agent)
                    .where(
                        Agent.deleted_at.is_(None),
                        Agent.name.in_(sorted(BUILTIN_AGENT_NAMES)),
                    )
                )
            ).scalar_one()
        if existing:
            return

        # dev.ps1 先启动后端再启动本地 MCP，等待它们在后台就绪后再做工具发现
        ready = await _wait_for_ports((8100, 8102, 8103), timeout_s=60.0)
        if not ready:
            log.warning("本地 MCP Server 未全部就绪，示例数据可能缺少工具绑定")

        async with _SessionFactory() as session:
            summary = await seed_demo_data(session)
        log.info("示例数据自动初始化完成：%s", summary)
    except asyncio.CancelledError:
        raise
    except Exception:  # 初始化失败不应阻断平台启动
        log.exception("自动初始化示例数据失败")


async def _wait_for_ports(
    ports: tuple[int, ...], *, host: str = "127.0.0.1", timeout_s: float = 60.0
) -> bool:
    """等待本机端口全部可连接，用于确认本地 MCP Server 已启动。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    pending = set(ports)
    while pending and loop.time() < deadline:
        for port in list(pending):
            try:
                _reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=1.0
                )
                writer.close()
                pending.discard(port)
            except Exception:
                continue
        if pending:
            await asyncio.sleep(2)
    return not pending


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
