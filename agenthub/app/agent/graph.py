"""LangGraph Agent Runtime 图。设计文档 §6.1、§6.4、§9。归属：A（Agent Runtime）。

图结构（与设计文档 §6.1 一致）::

    START -> model_node --有 tool_calls--> tools_node --+
                    |                                  |
                    +--无 tool_calls / 预算耗尽--> END <+
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.state import AgentState
from app.agent.stop_policy import StopPolicy
from app.core.enums import StepStatus, StopReason, TraceEventType
from app.mcp.gateway import McpToolGateway
from app.mcp.schemas import ToolCall, ToolContext, ToolDefinition, ToolResult
from app.schemas.agent import AgentRead
from app.trace.events import TraceEvent, TraceSink

MODEL_NODE = "model_node"
TOOLS_NODE = "tools_node"

# 契约 §7：写入 Trace 的 result_summary 截断长度
RESULT_SUMMARY_LIMIT = 2000
# 回填给模型的 Observation 上限，避免超大 Tool Result 撑爆上下文
OBSERVATION_LIMIT = 8000
# OpenAI-compatible 接口对 function name 的长度限制
_WIRE_NAME_MAX_LENGTH = 64


@dataclass
class RunContext:
    """单次 Run 的内部状态。

    由图节点写入、Runner 读取。挂在 `AgentState` 之外是为了让**失败路径**也能拿到
    计数与错误信息——`AgentState` 只承载与图执行相关的状态。
    """

    run_id: str
    agent_id: int
    stop_reason: StopReason | None = None
    error_code: str | None = None
    error_message: str | None = None
    llm_calls: int = 0
    tool_calls: int = 0


def encode_tool_name(qualified_name: str) -> str:
    """把 `qualified_name` 编码为合法的 LLM function name。

    契约中的 `qualified_name` 形如 `github.list_issues`，而 OpenAI-compatible 接口要求
    function name 匹配 `[a-zA-Z0-9_-]{1,64}`，其中的 `.` 不合法。因此对模型只暴露编码名，
    收到 `tool_call` 后再还原为 `qualified_name`；对外（Trace / SSE / DB）始终是原始值。
    """
    wire = qualified_name.replace(".", "__")
    if len(wire) > _WIRE_NAME_MAX_LENGTH:
        digest = hashlib.sha1(qualified_name.encode("utf-8")).hexdigest()[:8]
        wire = f"{wire[: _WIRE_NAME_MAX_LENGTH - 9]}_{digest}"
    return wire


def build_tool_schemas(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    """把 Tool Registry 的元数据转换为 OpenAI-compatible 的 function 描述。"""
    return [
        {
            "type": "function",
            "function": {
                "name": encode_tool_name(tool.qualified_name),
                "description": tool.description or tool.qualified_name,
                "parameters": tool.input_schema or {"type": "object", "properties": {}},
            },
        }
        for tool in tools
    ]


class ToolNameCodec:
    """Run 内「模型可见名 -> qualified_name」的还原表。"""

    def __init__(self, tools: list[ToolDefinition]) -> None:
        self._by_wire_name: dict[str, str] = {}
        for tool in tools:
            wire_name = encode_tool_name(tool.qualified_name)
            if wire_name in self._by_wire_name:
                raise ValueError(f"Tool 编码名冲突：{tool.qualified_name}")
            self._by_wire_name[wire_name] = tool.qualified_name

    def resolve(self, wire_name: str) -> str | None:
        """还原为 `qualified_name`；模型给出未绑定的名字时返回 None。"""
        return self._by_wire_name.get(wire_name)


def build_graph(
    *,
    model: BaseChatModel,
    gateway: McpToolGateway,
    tracer: TraceSink,
    agent: AgentRead,
    max_steps: int,
    candidates: list[ToolDefinition],
    ctx: RunContext,
    tool_timeout_ms: int = 30_000,
) -> CompiledStateGraph:
    """构建并编译单次 Run 使用的图。

    每次 Run 都会新建图：候选工具、`RunContext`、模型绑定都与该次 Run 一一对应。
    Checkpointer 使用内存实现（设计文档 §6.5），`thread_id` 由 Runner 传入。
    """
    policy = StopPolicy(max_steps)
    codec = ToolNameCodec(candidates)
    schemas = build_tool_schemas(candidates)
    bound_model = model.bind_tools(schemas) if schemas else model
    system_message = SystemMessage(agent.system_prompt) if agent.system_prompt else None
    candidate_names = [tool.qualified_name for tool in candidates]

    def _prompt_messages(history: list[BaseMessage]) -> list[BaseMessage]:
        """System Prompt 属于 AgentDefinition，不进 `AgentState.messages`。"""
        return [system_message, *history] if system_message else list(history)

    async def model_node(state: AgentState) -> dict[str, Any]:
        step_no = state["step_count"] + 1
        history = state["messages"]

        await tracer.emit(
            TraceEvent(
                run_id=ctx.run_id,
                step_no=step_no,
                event_type=TraceEventType.LLM_STARTED,
                status=StepStatus.RUNNING,
                node=MODEL_NODE,
                data={
                    "model": agent.model,
                    "message_count": len(history),
                    "candidate_tools": candidate_names,
                },
            )
        )

        started = time.perf_counter()
        try:
            response = await bound_model.ainvoke(_prompt_messages(history))
        except Exception as exc:  # 契约 §6.4 MODEL_ERROR：模型超时 / 鉴权 / 配额 / 解析错误
            ctx.llm_calls += 1
            ctx.stop_reason = StopReason.MODEL_ERROR
            ctx.error_code = "MODEL_ERROR"
            ctx.error_message = f"{type(exc).__name__}: {exc}"[:512]
            await tracer.emit(
                TraceEvent(
                    run_id=ctx.run_id,
                    step_no=step_no,
                    event_type=TraceEventType.LLM_FINISHED,
                    status=StepStatus.FAILED,
                    node=MODEL_NODE,
                    duration_ms=_elapsed_ms(started),
                    data={
                        "model": agent.model,
                        "error": {"code": ctx.error_code, "message": ctx.error_message},
                    },
                )
            )
            return {"step_count": step_no}

        duration_ms = _elapsed_ms(started)
        ctx.llm_calls += 1
        tool_call_count = len(getattr(response, "tool_calls", None) or [])
        answer_text = _text_of(response)

        update: dict[str, Any] = {"messages": [response], "step_count": step_no}
        if not tool_call_count or answer_text:
            # 无 tool_calls 时即最终答案；有 tool_calls 但带了文本时，它可能是
            # 「预算耗尽」场景下的部分产出，对应 RunStatus.PARTIAL（契约 §2.2）。
            update["final_answer"] = answer_text or None
        final_answer = update.get("final_answer", state["final_answer"])

        await tracer.emit(
            TraceEvent(
                run_id=ctx.run_id,
                step_no=step_no,
                event_type=TraceEventType.LLM_FINISHED,
                status=StepStatus.SUCCESS,
                node=MODEL_NODE,
                duration_ms=duration_ms,
                data={
                    "model": agent.model,
                    "token_usage": _token_usage(response),
                    "finish_reason": _finish_reason(response),
                    "tool_call_count": tool_call_count,
                },
            )
        )
        await tracer.emit(
            TraceEvent(
                run_id=ctx.run_id,
                step_no=step_no,
                event_type=TraceEventType.STATE_UPDATED,
                status=StepStatus.SUCCESS,
                node=MODEL_NODE,
                data={"step_count": step_no, "final_answer": final_answer},
            )
        )
        return update

    async def tools_node(state: AgentState) -> dict[str, Any]:
        history = state["messages"]
        raw_calls = list(getattr(history[-1], "tool_calls", None) or []) if history else []
        step_no = state["step_count"] + 1
        observations: list[ToolMessage] = []

        for raw in raw_calls:
            wire_name = str(raw.get("name") or "")
            arguments = dict(raw.get("args") or {})
            call_id = str(raw.get("id") or "")
            qualified_name = codec.resolve(wire_name)
            ctx.tool_calls += 1

            await tracer.emit(
                TraceEvent(
                    run_id=ctx.run_id,
                    step_no=step_no,
                    event_type=TraceEventType.TOOL_CALL_STARTED,
                    status=StepStatus.RUNNING,
                    node=TOOLS_NODE,
                    tool=qualified_name or wire_name,
                    data={"arguments": arguments},
                )
            )

            started = time.perf_counter()
            if qualified_name is None:
                # 模型给出了未绑定的 Tool：不抛异常，转为一次失败的工具调用
                result = ToolResult(
                    call_id=call_id,
                    qualified_name=wire_name,
                    ok=False,
                    error_code="TOOL_NOT_FOUND",
                    error_message=f"模型请求了未绑定的 Tool：{wire_name}",
                )
            else:
                result = await gateway.execute_tool(
                    ToolCall(call_id=call_id, qualified_name=qualified_name, arguments=arguments),
                    ToolContext(
                        run_id=ctx.run_id,
                        agent_id=ctx.agent_id,
                        step_no=step_no,
                        timeout_ms=tool_timeout_ms,
                    ),
                )

            observation = _render_observation(result)
            await tracer.emit(
                TraceEvent(
                    run_id=ctx.run_id,
                    step_no=step_no,
                    event_type=TraceEventType.TOOL_CALL_FINISHED,
                    status=StepStatus.SUCCESS if result.ok else StepStatus.FAILED,
                    node=TOOLS_NODE,
                    tool=result.qualified_name,
                    duration_ms=_elapsed_ms(started),
                    data={
                        "result_summary": observation[:RESULT_SUMMARY_LIMIT],
                        "truncated": len(observation) > RESULT_SUMMARY_LIMIT,
                        "result_bytes": len(observation.encode("utf-8")),
                        "error": None
                        if result.ok
                        else {"code": result.error_code, "message": result.error_message},
                    },
                )
            )
            observations.append(ToolMessage(content=observation, tool_call_id=call_id))

            if not result.ok:
                # 设计文档 §6.4：MCP 工具失败且策略不继续。
                # 仍会执行完本轮剩余调用，保证 assistant.tool_calls 与 ToolMessage 一一对应。
                ctx.stop_reason = StopReason.TOOL_ERROR
                ctx.error_code = result.error_code or "TOOL_EXECUTION_FAILED"
                ctx.error_message = result.error_message or "Tool 执行失败"

        await tracer.emit(
            TraceEvent(
                run_id=ctx.run_id,
                step_no=step_no,
                event_type=TraceEventType.STATE_UPDATED,
                status=StepStatus.SUCCESS,
                node=TOOLS_NODE,
                data={"step_count": step_no, "final_answer": None},
            )
        )
        return {"messages": observations, "step_count": step_no}

    def route_after_model(state: AgentState) -> str:
        if ctx.stop_reason is not None:
            return END
        if not _has_tool_calls(state["messages"][-1]):
            # 先判「模型给出了最终答案」：即使刚好用满预算，也属于正常结束而非 MAX_STEPS
            ctx.stop_reason = StopReason.FINISHED
            return END
        if policy.budget_exhausted(state["step_count"]):
            ctx.stop_reason = StopReason.MAX_STEPS
            return END
        return TOOLS_NODE

    def route_after_tools(state: AgentState) -> str:
        if ctx.stop_reason is not None:
            return END
        if policy.budget_exhausted(state["step_count"]):
            ctx.stop_reason = StopReason.MAX_STEPS
            return END
        return MODEL_NODE

    builder = StateGraph(AgentState)
    builder.add_node(MODEL_NODE, model_node)
    builder.add_node(TOOLS_NODE, tools_node)
    builder.add_edge(START, MODEL_NODE)
    builder.add_conditional_edges(MODEL_NODE, route_after_model, {TOOLS_NODE: TOOLS_NODE, END: END})
    builder.add_conditional_edges(TOOLS_NODE, route_after_tools, {MODEL_NODE: MODEL_NODE, END: END})
    return builder.compile(checkpointer=InMemorySaver())


def _has_tool_calls(message: BaseMessage) -> bool:
    return bool(getattr(message, "tool_calls", None))


def _text_of(message: BaseMessage) -> str:
    """取出消息的纯文本部分，兼容多段 content 的模型。"""
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _token_usage(message: BaseMessage) -> dict[str, int] | None:
    """映射为契约 §5.3 的 token_usage 结构。"""
    usage = getattr(message, "usage_metadata", None)
    if not usage:
        return None
    return {
        "prompt": int(usage.get("input_tokens", 0)),
        "completion": int(usage.get("output_tokens", 0)),
        "total": int(usage.get("total_tokens", 0)),
    }


def _finish_reason(message: BaseMessage) -> str | None:
    metadata = getattr(message, "response_metadata", None) or {}
    reason = metadata.get("finish_reason")
    return str(reason) if reason is not None else None


def _render_observation(result: ToolResult) -> str:
    """把 ToolResult 渲染为回填给模型的 Observation 文本。"""
    if result.ok:
        text = result.text or json.dumps(result.content, ensure_ascii=False)
        return text if len(text) <= OBSERVATION_LIMIT else text[:OBSERVATION_LIMIT] + "...(truncated)"
    return f"[tool_error] {result.error_code or 'TOOL_EXECUTION_FAILED'}: {result.error_message or ''}"


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
