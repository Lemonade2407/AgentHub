"""FastAPI 应用入口。归属：D（Platform Backend）。

本地启动（在 agenthub 目录下）：

    uvicorn app.main:app --reload --port 8001

端口与 `frontend/vite.config.ts` 的 `/api` 代理保持一致。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import agents, mcp, runs
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


@app.get("/api/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=True)
