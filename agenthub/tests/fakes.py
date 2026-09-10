"""A（Agent Runtime）测试用的替身与工厂。

用 `ScriptedChatModel` 替代真实 LLM，用 `FakeGateway` / `FakeSelector` / `FakeTracer`
替代 B、D 尚未实现的模块，从而让 A 的部分可以独立验证（设计文档 §17）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from app.core.enums import RiskLevel, TraceEventType
from app.mcp.schemas import ToolCall, ToolContext, ToolDefinition, ToolResult
from app.schemas.agent import AgentRead
from app.tools.selector import ToolCandidate
from app.trace.events import TraceEvent

FIXED_NOW = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)


def make_agent(**overrides: Any) -> AgentRead:
    base: dict[str, Any] = {
        "id": 1,
        "name": "Research Agent",
        "description": None,
        "model": "deepseek/deepseek-chat",
        "system_prompt": "你是一个研究员，优先使用工具获取事实。",
        "max_steps": 8,
        "enabled": True,
        "tool_ids": [1, 2],
        "created_at": FIXED_NOW,
        "updated_at": FIXED_NOW,
    }
    return AgentRead(**{**base, **overrides})


def make_tool(qualified_name: str, **overrides: Any) -> ToolDefinition:
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


class ModelBoom(RuntimeError):
    """模拟模型侧异常（超时 / 鉴权 / 配额）。"""


class ScriptedChatModel(BaseChatModel):
    """按脚本依次返回响应的 ChatModel。

    `script` 中的元素若是 `Exception`，则在对应那次调用时抛出。
    """

    script: list[Any] = Field(default_factory=list)
    calls: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tools: list[dict] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> BaseChatModel:  # type: ignore[override]
        self.bound_tools = [dict(tool) for tool in tools]
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        index = len(self.calls)
        self.calls.append(list(messages))
        if index >= len(self.script):
            raise ModelBoom(f"脚本已耗尽：第 {index + 1} 次调用没有预置响应")
        item = self.script[index]
        if isinstance(item, Exception):
            raise item
        return ChatResult(generations=[ChatGeneration(message=item)])


class FakeGateway:
    """`McpToolGateway` 的测试替身。"""

    def __init__(
        self,
        tools: list[ToolDefinition] | None = None,
        results: dict[str, ToolResult] | None = None,
        default_text: str = "工具执行成功",
    ) -> None:
        self.tools = tools or []
        self.results = results or {}
        self.default_text = default_text
        self.calls: list[ToolCall] = []
        self.contexts: list[ToolContext] = []
        self.listed_agent_ids: list[int] = []

    async def list_tools(self, *, agent_id: int) -> list[ToolDefinition]:
        self.listed_agent_ids.append(agent_id)
        return list(self.tools)

    async def execute_tool(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        self.calls.append(call)
        self.contexts.append(ctx)
        preset = self.results.get(call.qualified_name)
        if preset is not None:
            return preset.model_copy(update={"call_id": call.call_id})
        return ToolResult(
            call_id=call.call_id,
            qualified_name=call.qualified_name,
            ok=True,
            text=self.default_text,
            duration_ms=1,
        )


class FakeSelector:
    """`ToolSelector` 的测试替身。`picks` 为 None 时按 top_k 截断。"""

    def __init__(self, picks: list[str] | None = None, scores: dict[str, float] | None = None) -> None:
        self.picks = picks
        self.scores = scores or {}
        self.queries: list[str] = []
        self.top_ks: list[int] = []

    async def select(
        self,
        query: str,
        tools: list[ToolDefinition],
        top_k: int = 5,
    ) -> list[ToolCandidate]:
        self.queries.append(query)
        self.top_ks.append(top_k)
        if self.picks is None:
            return [
                ToolCandidate(tool=tool, score=round(1.0 - index * 0.1, 2))
                for index, tool in enumerate(tools[:top_k])
            ]
        by_name = {tool.qualified_name: tool for tool in tools}
        return [
            ToolCandidate(tool=by_name[name], score=self.scores.get(name, round(1.0 - index * 0.1, 2)))
            for index, name in enumerate(self.picks)
            if name in by_name
        ]


class ExplodingGateway(FakeGateway):
    """模拟违反契约、直接抛异常的实现，用于验证 INTERNAL_ERROR 兜底路径。"""

    async def execute_tool(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        raise RuntimeError("gateway 内部错误")


class FakeTracer:
    """`TraceSink` 的测试替身，按顺序收集事件。"""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)

    def types(self) -> list[TraceEventType]:
        return [event.event_type for event in self.events]

    def of(self, event_type: TraceEventType) -> list[TraceEvent]:
        return [event for event in self.events if event.event_type is event_type]

    def step_nos(self, event_type: TraceEventType) -> list[int]:
        return [event.step_no for event in self.of(event_type)]

    def tool_names(self) -> list[str]:
        return [event.tool for event in self.events if event.tool]
