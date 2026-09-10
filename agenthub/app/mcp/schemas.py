"""契约 §3.3 / §6.1 冻结 DTO。归属：B（MCP Hub）。

这些对象是 A（Runtime）与 B（MCP Hub）之间唯一的传递类型。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.enums import RiskLevel


class ToolDefinition(BaseModel):
    """Tool Registry 中的一条 Tool 元数据。"""

    id: int
    server_id: int
    server_name: str
    remote_name: str
    qualified_name: str
    description: str = ""
    input_schema: dict = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW_RISK
    enabled: bool = True
    updated_at: datetime


class ToolCall(BaseModel):
    """模型发起的一次工具调用（`qualified_name` 已由编码名还原）。"""

    call_id: str
    qualified_name: str
    arguments: dict = Field(default_factory=dict)


class ToolContext(BaseModel):
    """一次工具调用的执行上下文。"""

    run_id: str
    agent_id: int
    step_no: int
    timeout_ms: int = 30_000


class ToolResult(BaseModel):
    """工具执行结果。

    契约 §6.1 约定：`McpToolGateway.execute_tool` 不抛业务异常，
    失败一律以 `ok=False` + `error_code` 返回。
    """

    call_id: str
    qualified_name: str
    ok: bool
    content: list[dict] = Field(default_factory=list)
    text: str = ""
    duration_ms: int = 0
    error_code: str | None = None
    error_message: str | None = None
