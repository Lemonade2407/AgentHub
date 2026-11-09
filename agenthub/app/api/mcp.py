"""MCP 管理路由。契约 §4.2。归属：D（Platform Backend）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_factory
from app.core.config import Settings, get_settings
from app.core.enums import McpServerStatus, RiskLevel
from app.db.session import get_session
from app.mcp.client_adapter import HttpMcpClientFactory
from app.mcp.schemas import McpDiscoverResult, McpServerTestResult, ToolDefinition
from app.repositories.mcp_repository import McpServerRepository, McpToolRepository
from app.schemas.common import Page
from app.schemas.mcp import (
    McpServerCreate,
    McpServerRead,
    McpServerUpdate,
    ToolTestRequest,
    ToolTestResult,
)
from app.services.mcp_service import McpService, validate_endpoint

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.post("/servers", response_model=McpServerRead, status_code=201)
async def create_server(
    payload: McpServerCreate,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> McpServerRead:
    validate_endpoint(payload.endpoint, allow_private=settings.allow_private_mcp)
    server = await McpServerRepository(session).create(payload)
    await session.commit()
    return server


@router.get("/servers", response_model=Page[McpServerRead])
async def list_servers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: McpServerStatus | None = None,
    session: AsyncSession = Depends(get_session),
) -> Page[McpServerRead]:
    items, total = await McpServerRepository(session).list(
        page=page, page_size=page_size, status=status
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/servers/{server_id}", response_model=McpServerRead)
async def get_server(
    server_id: int,
    session: AsyncSession = Depends(get_session),
) -> McpServerRead:
    return await McpServerRepository(session).get(server_id)


@router.put("/servers/{server_id}", response_model=McpServerRead)
async def update_server(
    server_id: int,
    payload: McpServerUpdate,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    client_factory: HttpMcpClientFactory = Depends(get_client_factory),
) -> McpServerRead:
    if payload.endpoint is not None:
        validate_endpoint(payload.endpoint, allow_private=settings.allow_private_mcp)

    server, changed_connection = await McpServerRepository(session).update(server_id, payload)
    await session.commit()
    if changed_connection:
        await client_factory.invalidate(server_id)
    return server


@router.post("/servers/{server_id}/test", response_model=McpServerTestResult)
async def test_server(
    server_id: int,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    client_factory: HttpMcpClientFactory = Depends(get_client_factory),
) -> McpServerTestResult:
    service = McpService(
        session, client_factory, allow_private_mcp=settings.allow_private_mcp
    )
    result = await service.test_connection(server_id)
    await session.commit()
    return result


@router.post("/servers/{server_id}/discover", response_model=McpDiscoverResult)
async def discover_server(
    server_id: int,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    client_factory: HttpMcpClientFactory = Depends(get_client_factory),
) -> McpDiscoverResult:
    service = McpService(
        session, client_factory, allow_private_mcp=settings.allow_private_mcp
    )
    result = await service.discover(server_id)
    await session.commit()
    return result


@router.get("/tools", response_model=Page[ToolDefinition])
async def list_tools(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    server_id: int | None = None,
    enabled: bool | None = None,
    risk_level: RiskLevel | None = None,
    keyword: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> Page[ToolDefinition]:
    items, total = await McpToolRepository(session).list(
        page=page,
        page_size=page_size,
        server_id=server_id,
        enabled=enabled,
        risk_level=risk_level,
        keyword=keyword,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("/tools/{tool_id}/test", response_model=ToolTestResult)
async def test_tool(
    tool_id: int,
    payload: ToolTestRequest,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    client_factory: HttpMcpClientFactory = Depends(get_client_factory),
) -> ToolTestResult:
    service = McpService(
        session, client_factory, allow_private_mcp=settings.allow_private_mcp
    )
    return await service.test_tool(tool_id, payload.arguments)
