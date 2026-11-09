<<<<<<< HEAD
"""契约 §3.2 / §3.3 —— MCP Server 与 Tool DTO。

冻结来源：AgentHub_接口契约文档.md §3.2、§3.3。
注意：`McpServerRead` 不回传 `headers`；见契约"headers 永不回传"。
"""
=======
"""MCP 管理相关 DTO。契约 §3.2 / §3.3。归属：D（Platform Backend）。"""
>>>>>>> 47840490efc0088f6d22732094d9c57c7571fb6e

from __future__ import annotations

from datetime import datetime
<<<<<<< HEAD

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import McpServerStatus, RiskLevel, TransportType


# ---------- Mcp Server ----------
=======
from typing import Any

from pydantic import BaseModel, Field

from app.core.enums import McpServerStatus, TransportType
>>>>>>> 47840490efc0088f6d22732094d9c57c7571fb6e


class McpServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    endpoint: str = Field(min_length=1, max_length=512)
    transport: TransportType = TransportType.STREAMABLE_HTTP
    description: str | None = Field(default=None, max_length=512)
<<<<<<< HEAD
    enabled: bool = True
=======
>>>>>>> 47840490efc0088f6d22732094d9c57c7571fb6e
    headers: dict[str, str] | None = None


class McpServerUpdate(BaseModel):
<<<<<<< HEAD
    """PUT 部分更新。

    约束：`name` 注册后不可修改（契约 §10 D6）；
    请求体中若含 `name` 会被后端忽略，不报错。
    """

    endpoint: str | None = Field(default=None, max_length=512)
    transport: TransportType | None = None
    description: str | None = Field(default=None, max_length=512)
    enabled: bool | None = None
=======
    endpoint: str | None = Field(default=None, min_length=1, max_length=512)
    transport: TransportType | None = None
    description: str | None = Field(default=None, max_length=512)
>>>>>>> 47840490efc0088f6d22732094d9c57c7571fb6e
    headers: dict[str, str] | None = None


class McpServerRead(BaseModel):
<<<<<<< HEAD
    """不含 headers（敏感字段，永不回传）。"""

    model_config = ConfigDict(from_attributes=True)

=======
>>>>>>> 47840490efc0088f6d22732094d9c57c7571fb6e
    id: int
    name: str
    endpoint: str
    transport: TransportType
    description: str | None
    enabled: bool
    status: McpServerStatus
<<<<<<< HEAD
    tool_count: int = 0
    last_error: str | None
    last_discovered_at: datetime | None
=======
    last_error: str | None
    last_discovered_at: datetime | None
    tool_count: int
>>>>>>> 47840490efc0088f6d22732094d9c57c7571fb6e
    created_at: datetime
    updated_at: datetime


<<<<<<< HEAD
class McpServerTestResult(BaseModel):
    ok: bool
    status: McpServerStatus
    latency_ms: int
    server_info: dict | None = None
    error_code: str | None = None
    error_message: str | None = None


class McpDiscoverResult(BaseModel):
    server_id: int
    status: McpServerStatus
    added: int
    updated: int
    removed: int
    total: int
    duration_ms: int
    error_code: str | None = None
    error_message: str | None = None


# ---------- Tool ----------


class ToolDefinition(BaseModel):
    """Tool 元数据（`mcp_tool` + 关联 `mcp_server.name` 组合）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    server_id: int
    server_name: str
    remote_name: str
    qualified_name: str
    description: str
    input_schema: dict
    risk_level: RiskLevel
    enabled: bool
    updated_at: datetime


class ToolTestRequest(BaseModel):
    arguments: dict = Field(default_factory=dict)


class ToolTestResult(BaseModel):
    ok: bool
    duration_ms: int
    content: list[dict] | None = None
    is_error: bool = False
=======
class ToolTestRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolTestResult(BaseModel):
    success: bool
    tool: str
    duration_ms: int
    content: list[dict[str, Any]]
    is_error: bool
>>>>>>> 47840490efc0088f6d22732094d9c57c7571fb6e
    error_code: str | None = None
    error_message: str | None = None
