"""MCP Server CRUD + Tool 查询（契约 §4.2）。

动作接口（test / discover / tool.test）在 V1 后端还需接入 MCP Gateway 做实际连通性探测，
本次先实现完整骨架，返回 stub 的成功态（status=UNKNOWN / ok=false），等 gateway 接入后
再替换 async 探测实现。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AgentHubHTTPException, conflict, not_found
from app.core.db import get_session
from app.core.enums import McpServerStatus
from app.models.mcp import McpServer, McpTool
from app.schemas.common import Page
from app.schemas.mcp import (
    McpDiscoverResult,
    McpServerCreate,
    McpServerRead,
    McpServerTestResult,
    McpServerUpdate,
    ToolDefinition,
    ToolTestRequest,
    ToolTestResult,
)

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


# ---------- helpers ----------


async def _server_or_404(session: AsyncSession, server_id: int) -> McpServer:
    server = (
        await session.execute(select(McpServer).where(McpServer.id == server_id))
    ).scalar_one_or_none()
    if server is None:
        raise not_found(f"McpServer {server_id} not found")
    return server


async def _tool_or_404(session: AsyncSession, tool_id: int) -> McpTool:
    tool = (
        await session.execute(select(McpTool).where(McpTool.id == tool_id))
    ).scalar_one_or_none()
    if tool is None:
        raise not_found(f"McpTool {tool_id} not found")
    return tool


async def _server_tool_count(session: AsyncSession, server_id: int) -> int:
    return (
        await session.execute(
            select(func.count(McpTool.id)).where(McpTool.server_id == server_id)
        )
    ).scalar_one() or 0


async def _build_server_read(session: AsyncSession, server: McpServer) -> McpServerRead:
    return McpServerRead(
        id=server.id,
        name=server.name,
        endpoint=server.endpoint,
        transport=server.transport,  # type: ignore[arg-type]  # StrEnum 值转 enum
        description=server.description,
        enabled=server.enabled,
        status=server.status,  # type: ignore[arg-type]
        tool_count=await _server_tool_count(session, server.id),
        last_error=server.last_error,
        last_discovered_at=server.last_discovered_at,
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


# ---------- 4.2.1 注册 ----------


@router.post("/servers", response_model=McpServerRead, status_code=status.HTTP_201_CREATED)
async def create_server(
    payload: McpServerCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> McpServerRead:
    server = McpServer(
        name=payload.name,
        endpoint=payload.endpoint,
        transport=payload.transport.value,
        description=payload.description,
        enabled=payload.enabled,
        headers=payload.headers,
        status=McpServerStatus.UNKNOWN.value,
    )
    session.add(server)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise conflict("mcp server name already exists")
    await session.refresh(server)
    return await _build_server_read(session, server)


# ---------- 4.2.2 列表 ----------


@router.get("/servers", response_model=Page[McpServerRead])
async def list_servers(
    session: Annotated[AsyncSession, Depends(get_session)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_: str | None = Query(default=None, alias="status"),
) -> Page[McpServerRead]:
    conditions: list = []
    if status_ is not None:
        conditions.append(McpServer.status == status_)

    stmt = select(McpServer).where(*conditions)
    total = (
        await session.execute(select(func.count(McpServer.id)).where(*conditions))
    ).scalar_one()

    offset = (page - 1) * page_size
    servers = (
        (await session.execute(stmt.order_by(McpServer.created_at.desc()).offset(offset).limit(page_size)))
        .scalars()
        .all()
    )

    items = [await _build_server_read(session, s) for s in servers]
    return Page(items=items, total=total, page=page, page_size=page_size)


# ---------- 4.2.3 详情 ----------


@router.get("/servers/{server_id}", response_model=McpServerRead)
async def get_server(
    server_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> McpServerRead:
    server = await _server_or_404(session, server_id)
    return await _build_server_read(session, server)


# ---------- 4.2.4 修改 ----------


@router.put("/servers/{server_id}", response_model=McpServerRead)
async def update_server(
    server_id: int,
    payload: McpServerUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> McpServerRead:
    server = await _server_or_404(session, server_id)

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        return await _build_server_read(session, server)

    for k, v in update_data.items():
        # transport 是 StrEnum，落库用 .value
        setattr(server, k, v.value if hasattr(v, "value") else v)

    # endpoint / transport / headers 变更 → 状态重置
    if any(k in update_data for k in ("endpoint", "transport", "headers")):
        server.status = McpServerStatus.UNKNOWN.value
        server.last_error = None

    await session.commit()
    await session.refresh(server)
    return await _build_server_read(session, server)


# ---------- 4.2.5 连通性测试（stub） ----------


@router.post("/servers/{server_id}/test", response_model=McpServerTestResult)
async def test_server(
    server_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> McpServerTestResult:
    # V1 stub：实际探测接入 mcp.gateway 后替换
    server = await _server_or_404(session, server_id)
    latency = 50  # ms
    server.status = McpServerStatus.ERROR.value
    server.last_error = "test not implemented yet"
    await session.commit()
    return McpServerTestResult(
        ok=False,
        status=McpServerStatus.ERROR,
        latency_ms=latency,
        error_code="INTERNAL_ERROR",
        error_message="MCP Gateway 未接入，占位 stub",
    )


# ---------- 4.2.6 重新发现 Tool（stub） ----------


@router.post("/servers/{server_id}/discover", response_model=McpDiscoverResult)
async def discover_tools(
    server_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> McpDiscoverResult:
    server = await _server_or_404(session, server_id)
    duration = 10
    server.status = McpServerStatus.ERROR.value
    server.last_error = "discover not implemented yet"
    await session.commit()
    return McpDiscoverResult(
        server_id=server.id,
        status=McpServerStatus.ERROR,
        added=0,
        updated=0,
        removed=0,
        total=0,
        duration_ms=duration,
        error_code="INTERNAL_ERROR",
        error_message="MCP Gateway 未接入，占位 stub",
    )


# ---------- 4.2.7 查询 Tool ----------


@router.get("/tools", response_model=Page[ToolDefinition])
async def list_tools(
    session: Annotated[AsyncSession, Depends(get_session)],
    server_id: int | None = None,
    enabled: bool | None = None,
    risk_level: str | None = None,
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> Page[ToolDefinition]:
    conditions: list = []
    if server_id is not None:
        conditions.append(McpTool.server_id == server_id)
    if enabled is not None:
        conditions.append(McpTool.enabled == enabled)
    if risk_level is not None:
        conditions.append(McpTool.risk_level == risk_level)
    if keyword:
        conditions.append(
            (McpTool.remote_name.ilike(f"%{keyword}%"))
            | (McpTool.description.ilike(f"%{keyword}%"))
        )

    stmt = select(McpTool, McpServer.name.label("server_name")).join(
        McpServer, McpTool.server_id == McpServer.id
    )
    from sqlalchemy import and_

    # count —— 子查询写法，与 list_agents / list_servers 保持一致、更稳健
    count_sub = select(McpTool.id).join(
        McpServer, McpTool.server_id == McpServer.id
    )
    if conditions:
        where = and_(*conditions)
        stmt = stmt.where(where)
        count_sub = count_sub.where(where)

    total = (
        await session.execute(select(func.count()).select_from(count_sub.subquery()))
    ).scalar_one()

    offset = (page - 1) * page_size
    stmt = stmt.order_by(McpTool.created_at.desc()).offset(offset).limit(page_size)
    rows = (await session.execute(stmt)).all()

    items = [
        ToolDefinition(
            id=tool.id,
            server_id=tool.server_id,
            server_name=sname,
            remote_name=tool.remote_name,
            qualified_name=tool.qualified_name,
            description=tool.description,
            input_schema=tool.input_schema or {},
            risk_level=tool.risk_level,  # type: ignore[arg-type]
            enabled=tool.enabled,
            updated_at=tool.updated_at,
        )
        for tool, sname in rows
    ]
    return Page(items=items, total=total, page=page, page_size=page_size)


# ---------- 4.2.8 手动测试 Tool（stub） ----------


@router.post("/tools/{tool_id}/test", response_model=ToolTestResult)
async def test_tool(
    tool_id: int,
    payload: ToolTestRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ToolTestResult:
    await _tool_or_404(session, tool_id)
    return ToolTestResult(
        ok=False,
        duration_ms=10,
        is_error=True,
        error_code="INTERNAL_ERROR",
        error_message="MCP Gateway 未接入，占位 stub",
    )
