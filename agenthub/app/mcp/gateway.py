"""契约 §6.1 冻结接口：A 调用、B 实现。归属：B（MCP Hub）。

实现位置建议：`app/mcp/router.py`（Tool Router）+ `app/mcp/client_adapter.py`。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.mcp.schemas import ToolCall, ToolContext, ToolDefinition, ToolResult


@runtime_checkable
class McpToolGateway(Protocol):
    """Agent Runtime 访问 MCP Tool 的唯一入口。"""

    async def list_tools(self, *, agent_id: int) -> list[ToolDefinition]:
        """返回该 Agent 已绑定且 `enabled` 的 Tool。"""

    async def execute_tool(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        """执行单个 Tool Call。

        内部依次完成：Registry 查询 → Permission Guard → input_schema 校验 → MCP `tools/call`。
        约定：**不抛业务异常**，失败一律以 `ToolResult(ok=False, error_code=...)` 返回。
        """
