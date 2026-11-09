"""MCP 管理服务：连通性测试、Discovery、Tool 手动测试。归属：D（Platform Backend）。"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.mcp.client_adapter import (
    MCP_DISCOVERY_FAILED,
    MCP_SERVER_UNREACHABLE,
    TOOL_EXECUTION_FAILED,
    TOOL_TIMEOUT,
    HttpMcpClientFactory,
    McpClientError,
)
from app.mcp.discovery import DiscoveryService, McpDiscoveryError
from app.mcp.router import flatten_content, validate_arguments
from app.mcp.schemas import McpDiscoverResult, McpServerTestResult, ToolDefinition
from app.repositories.mcp_repository import McpServerRepository, McpToolRepository
from app.schemas.mcp import ToolTestResult
from app.tools.permission import PermissionGuard, ToolPermissionDenied

logger = logging.getLogger(__name__)

TOOL_TEST_TIMEOUT_S = 30.0
_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "metadata.google.internal"}


def validate_endpoint(endpoint: str, *, allow_private: bool) -> None:
    """契约 §4.2.1：只允许 http/https，默认拒绝 loopback、私网与链路本地地址。"""
    parts = urlsplit(endpoint)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise AppError(
            "INVALID_ARGUMENT",
            "endpoint 必须是合法的 http/https 地址",
            http_status=400,
        )

    host = parts.hostname.lower()
    if host in _BLOCKED_HOSTNAMES and not allow_private:
        raise AppError(
            "INVALID_ARGUMENT",
            f"endpoint 不允许指向本机或云元数据地址：{host}",
            http_status=400,
        )

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return

    if address.is_link_local or address.is_multicast or address.is_unspecified:
        raise AppError(
            "INVALID_ARGUMENT",
            f"endpoint 不允许指向链路本地 / 组播 / 未指定地址：{host}",
            http_status=400,
        )
    if (address.is_loopback or address.is_private) and not allow_private:
        raise AppError(
            "INVALID_ARGUMENT",
            f"endpoint 不允许指向私网地址：{host}",
            http_status=400,
        )


class McpService:
    def __init__(
        self,
        session: AsyncSession,
        client_factory: HttpMcpClientFactory,
        *,
        allow_private_mcp: bool = False,
    ) -> None:
        self._session = session
        self._client_factory = client_factory
        self._allow_private_mcp = allow_private_mcp

    def _discovery_service(self) -> DiscoveryService:
        return DiscoveryService(
            registry_store=McpToolRepository(self._session),
            server_store=McpServerRepository(self._session),
            client_factory=self._client_factory,
        )

    async def test_connection(self, server_id: int) -> McpServerTestResult:
        config = await McpServerRepository(self._session).get_config(server_id)
        if config is None:
            raise AppError("NOT_FOUND", f"MCP Server 不存在：{server_id}", http_status=404)
        return await self._discovery_service().test_connection(config)

    async def discover(self, server_id: int) -> McpDiscoverResult:
        config = await McpServerRepository(self._session).get_config(server_id)
        if config is None:
            raise AppError("NOT_FOUND", f"MCP Server 不存在：{server_id}", http_status=404)

        try:
            result = await self._discovery_service().discover(config)
        except McpDiscoveryError as exc:
            # DiscoveryService 已把 status=ERROR 写回内存对象，需要提交后再抛
            await self._session.commit()
            raise AppError(
                MCP_DISCOVERY_FAILED, exc.message, http_status=502
            ) from exc
        return result

    async def test_tool(self, tool_id: int, arguments: dict) -> ToolTestResult:
        tool = await McpToolRepository(self._session).get(tool_id)
        if tool is None:
            raise AppError("NOT_FOUND", f"Tool 不存在：{tool_id}", http_status=404)

        self._check_permission(tool)

        if error := validate_arguments(tool.input_schema, arguments):
            raise AppError(
                "TOOL_SCHEMA_INVALID",
                "入参不符合 input_schema",
                http_status=422,
                detail={"error": error},
            )

        config = await McpServerRepository(self._session).get_config(tool.server_id)
        if config is None:
            raise AppError(
                MCP_SERVER_UNREACHABLE,
                f"MCP Server 不存在：{tool.server_id}",
                http_status=502,
            )

        client = self._client_factory.for_server(config)
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                client.call_tool(tool.remote_name, arguments),
                timeout=TOOL_TEST_TIMEOUT_S,
            )
        except TimeoutError as exc:
            raise AppError(
                TOOL_TIMEOUT,
                f"Tool 调用超时（{TOOL_TEST_TIMEOUT_S}s）",
                http_status=504,
            ) from exc
        except McpClientError as exc:
            raise AppError(exc.error_code, exc.message, http_status=502) from exc

        duration_ms = int((time.perf_counter() - started) * 1000)
        text = flatten_content(result.content)
        return ToolTestResult(
            success=not result.is_error,
            tool=tool.qualified_name,
            duration_ms=duration_ms,
            content=result.content,
            is_error=result.is_error,
            error_code=TOOL_EXECUTION_FAILED if result.is_error else None,
            error_message=(text[:512] if result.is_error else None),
        )

    @staticmethod
    def _check_permission(tool: ToolDefinition) -> None:
        try:
            PermissionGuard().check(agent_id=None, tool=tool)
        except ToolPermissionDenied as exc:
            raise AppError(exc.error_code, exc.message, http_status=403) from exc
