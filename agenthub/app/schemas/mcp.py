"""MCP 管理相关 DTO。契约 §3.2 / §3.3。归属：D（Platform Backend）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.enums import McpServerStatus, TransportType


class McpServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    endpoint: str = Field(min_length=1, max_length=512)
    transport: TransportType = TransportType.STREAMABLE_HTTP
    description: str | None = Field(default=None, max_length=512)
    headers: dict[str, str] | None = None


class McpServerUpdate(BaseModel):
    endpoint: str | None = Field(default=None, min_length=1, max_length=512)
    transport: TransportType | None = None
    description: str | None = Field(default=None, max_length=512)
    headers: dict[str, str] | None = None


class McpServerRead(BaseModel):
    id: int
    name: str
    endpoint: str
    transport: TransportType
    description: str | None
    enabled: bool
    status: McpServerStatus
    last_error: str | None
    last_discovered_at: datetime | None
    tool_count: int
    created_at: datetime
    updated_at: datetime


class ToolTestRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolTestResult(BaseModel):
    success: bool
    tool: str
    duration_ms: int
    content: list[dict[str, Any]]
    is_error: bool
    error_code: str | None = None
    error_message: str | None = None
