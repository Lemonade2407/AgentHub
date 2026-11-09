"""Tool Registry。设计文档 §8.1 / 契约 §6.1。归属：B（MCP Hub）。

Registry 是 `mcp_tool` + `agent_tool` 的读模型：Router 只通过它拿到
`ToolDefinition`，不直接触碰数据库。因此本模块用 Protocol 定义边界，
D 提供 SQLAlchemy 实现，B 提供内存实现用于测试与本地联调。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.mcp.schemas import ToolDefinition


@runtime_checkable
class ToolRegistry(Protocol):
    """`ToolDefinition` 的查询边界。"""

    async def get_by_qualified_name(self, qualified_name: str) -> ToolDefinition | None:
        """按 `qualified_name` 查 Tool（不做绑定 / 启用过滤）。不存在返回 None。"""

    async def list_bound_tools(self, *, agent_id: int) -> list[ToolDefinition]:
        """返回该 Agent 已绑定且 `enabled` 的 Tool（契约 §6.1 `list_tools` 的语义）。"""

    async def is_bound(self, *, agent_id: int, tool_id: int) -> bool:
        """该 Agent 是否绑定了该 Tool（不看 `enabled`）。"""


class InMemoryToolRegistry:
    """基于进程内字典的实现，供测试与无 DB 场景使用。"""

    def __init__(
        self,
        tools: list[ToolDefinition] | None = None,
        bindings: dict[int, set[int]] | None = None,
    ) -> None:
        self._tools: dict[int, ToolDefinition] = {tool.id: tool for tool in tools or []}
        self._by_qualified_name: dict[str, ToolDefinition] = {
            tool.qualified_name: tool for tool in tools or []
        }
        self._bindings: dict[int, set[int]] = {
            agent_id: set(tool_ids) for agent_id, tool_ids in (bindings or {}).items()
        }

    async def get_by_qualified_name(self, qualified_name: str) -> ToolDefinition | None:
        return self._by_qualified_name.get(qualified_name)

    async def list_bound_tools(self, *, agent_id: int) -> list[ToolDefinition]:
        bound_ids = self._bindings.get(agent_id, set())
        return sorted(
            (tool for tool in self._tools.values() if tool.enabled and tool.id in bound_ids),
            key=lambda tool: tool.id,
        )

    async def is_bound(self, *, agent_id: int, tool_id: int) -> bool:
        return tool_id in self._bindings.get(agent_id, set())

    def bind(self, agent_id: int, tool_ids: list[int]) -> None:
        """全量覆盖某 Agent 的绑定（契约 §3.1 `PUT /api/agents/{id}/tools`）。"""
        self._bindings[agent_id] = set(tool_ids)
