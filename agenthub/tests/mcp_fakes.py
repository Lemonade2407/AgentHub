"""B（MCP Hub）测试用的替身。

用 `FakeMcpClient` 替代真实 MCP Server，用 `InMemoryToolRegistry`（app 内实现）
替代 DB Registry，从而让 B 的逻辑可完全离线单测（设计文档 §17）。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.core.enums import McpServerStatus, RiskLevel
from app.mcp.client_adapter import (
    McpCallResult,
    McpServerConfig,
    McpToolInfo,
)
from app.mcp.discovery import NormalizedTool, ToolUpsertOutcome
from app.mcp.schemas import ToolDefinition

FIXED_NOW = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)


def make_tool(qualified_name: str, **overrides: Any) -> ToolDefinition:
    """构造一条 `ToolDefinition`（B 侧测试不依赖 A 的 langchain 替身）。"""
    server_slug, _, remote_name = qualified_name.partition(".")
    base: dict[str, Any] = {
        "id": 1,
        "server_id": 1,
        "server_name": server_slug,
        "remote_name": remote_name,
        "qualified_name": qualified_name,
        "description": f"{remote_name} 工具",
        "input_schema": {"type": "object", "properties": {}},
        "risk_level": RiskLevel.READ_ONLY,
        "enabled": True,
        "updated_at": FIXED_NOW,
    }
    return ToolDefinition(**{**base, **overrides})


def make_server(**overrides: object) -> McpServerConfig:
    base: dict[str, object] = {
        "id": 1,
        "name": "github",
        "endpoint": "http://demo-mcp:8100/mcp",
    }
    return McpServerConfig(**{**base, **overrides})


def make_tool_info(name: str, **overrides: object) -> McpToolInfo:
    base: dict[str, object] = {
        "name": name,
        "description": f"{name} 工具",
        "input_schema": {"type": "object", "properties": {}},
    }
    return McpToolInfo(**{**base, **overrides})


class FakeMcpClient:
    """`McpClientAdapter` 的测试替身。"""

    def __init__(
        self,
        *,
        server_info: dict | None = None,
        tools: list[McpToolInfo] | None = None,
        results: dict[str, McpCallResult] | None = None,
        init_error: Exception | None = None,
        list_error: Exception | None = None,
        call_error: Exception | None = None,
        delay_s: float = 0.0,
    ) -> None:
        self.server_info = server_info or {"name": "demo", "version": "1.0"}
        self.tools = tools or []
        self.results = results or {}
        self.init_error = init_error
        self.list_error = list_error
        self.call_error = call_error
        self.delay_s = delay_s
        self.call_arguments: list[tuple[str, dict]] = []

    async def initialize(self) -> dict:
        if self.init_error is not None:
            raise self.init_error
        return self.server_info

    async def list_tools(self) -> list[McpToolInfo]:
        if self.list_error is not None:
            raise self.list_error
        return list(self.tools)

    async def call_tool(self, remote_name: str, arguments: dict) -> McpCallResult:
        self.call_arguments.append((remote_name, arguments))
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.call_error is not None:
            raise self.call_error
        preset = self.results.get(remote_name)
        if preset is not None:
            return preset
        return McpCallResult(content=[{"type": "text", "text": f"{remote_name} 执行成功"}])


class FakeMcpClientFactory:
    """`McpClientFactory` 的测试替身。`clients` 为空时对所有 Server 返回同一个 client。"""

    def __init__(self, client: FakeMcpClient | None = None, clients: dict[int, FakeMcpClient] | None = None) -> None:
        self.client = client or FakeMcpClient()
        self.clients = clients
        self.requested_server_ids: list[int] = []

    def for_server(self, server: McpServerConfig) -> FakeMcpClient:
        self.requested_server_ids.append(server.id)
        if self.clients is not None:
            return self.clients[server.id]
        return self.client


class FakeServerProvider:
    """`McpServerProvider` 的测试替身。"""

    def __init__(self, servers: list[McpServerConfig] | None = None) -> None:
        self.servers = {server.id: server for server in servers or []}

    async def get(self, server_id: int) -> McpServerConfig | None:
        return self.servers.get(server_id)


class InMemoryToolRegistryStore:
    """`ToolRegistryStore` 的测试替身，实现 upsert / 置禁用 / 计数语义。"""

    def __init__(self, existing: list[NormalizedTool] | None = None) -> None:
        self.tools: dict[tuple[int, str], NormalizedTool] = {
            (tool.server_id, tool.remote_name): tool for tool in existing or []
        }

    async def upsert_tool(self, tool: NormalizedTool) -> ToolUpsertOutcome:
        key = (tool.server_id, tool.remote_name)
        outcome = ToolUpsertOutcome.UPDATED if key in self.tools else ToolUpsertOutcome.ADDED
        self.tools[key] = tool
        return outcome

    async def disable_tools_not_returned(self, *, server_id: int, remote_names: set[str]) -> int:
        disabled = 0
        for key, tool in self.tools.items():
            if key[0] == server_id and key[1] not in remote_names and tool.enabled:
                self.tools[key] = tool.model_copy(update={"enabled": False})
                disabled += 1
        return disabled

    async def count_tools(self, *, server_id: int) -> int:
        return sum(1 for sid, _ in self.tools if sid == server_id)


class RecordingServerStore:
    """`McpServerStore` 的测试替身，记录状态回写。"""

    def __init__(self) -> None:
        self.status_updates: list[tuple[int, McpServerStatus, str | None]] = []
        self.discoveries: list[tuple[int, datetime]] = []

    async def update_status(
        self, *, server_id: int, status: McpServerStatus, last_error: str | None
    ) -> None:
        self.status_updates.append((server_id, status, last_error))

    async def mark_discovered(self, *, server_id: int, discovered_at: datetime) -> None:
        self.discoveries.append((server_id, discovered_at))


__all__ = [
    "FakeMcpClient",
    "FakeMcpClientFactory",
    "FakeServerProvider",
    "InMemoryToolRegistryStore",
    "RecordingServerStore",
    "make_server",
    "make_tool",
    "make_tool_info",
]
