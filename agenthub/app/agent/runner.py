"""AgentRunner —— Agent 执行入口。设计文档 §6.3 / 契约 §6.2。归属：A（Agent Runtime）。

职责（对应设计文档 §6.3）：
1. 加载 AgentDefinition（由调用方通过 `agent` 传入）；
2. 获取 Agent 已绑定工具；
3. 调用 ToolSelector 得到 Top-K 候选工具；
4. 构建 compiled LangGraph；
5. 使用异步 streaming 执行；
6. 将执行过程映射为 TraceEvent；
7. 在成功 / 超限 / 模型错误 / 工具错误时统一结束 Run。

本模块不依赖 FastAPI、SQLAlchemy 与 Response 对象（设计文档 §3.1），
因此可被 API 层、测试与脚本直接复用。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.agent.graph import RunContext, build_graph
from app.agent.model_provider import build_chat_model
from app.agent.state import AgentState
from app.agent.stop_policy import StopPolicy
from app.core.enums import RunStatus, StepStatus, StopReason, TraceEventType
from app.mcp.gateway import McpToolGateway
from app.mcp.schemas import ToolDefinition
from app.schemas.agent import AgentRead
from app.tools.selector import ToolSelector
from app.trace.events import TraceEvent, TraceSink

DEFAULT_TOP_K = 5
DEFAULT_TOOL_TIMEOUT_MS = 30_000

logger = logging.getLogger(__name__)


class RunResult(BaseModel):
    """契约 §6.2 —— 一次 Run 的最终结果，由调用方（D）落库并回写 Run 状态。"""

    run_id: str
    status: RunStatus
    stop_reason: StopReason
    output: str | None
    llm_calls: int
    tool_calls: int
    step_count: int
    duration_ms: int
    error_code: str | None = None
    error_message: str | None = None


class AgentRunner:
    """契约 §6.2 的实现。

    `tool_selector` 为 None 时不做动态筛选，直接把全部绑定工具注入模型；
    该开关对应设计文档 §7 的"动态 Tool Selection 属 P1 可独立开关"。
    """

    def __init__(
        self,
        *,
        gateway: McpToolGateway,
        tool_selector: ToolSelector | None = None,
        model_factory: Callable[[str], BaseChatModel] = build_chat_model,
        top_k: int = DEFAULT_TOP_K,
        tool_timeout_ms: int = DEFAULT_TOOL_TIMEOUT_MS,
    ) -> None:
        self._gateway = gateway
        self._selector = tool_selector
        self._model_factory = model_factory
        self._top_k = top_k
        self._tool_timeout_ms = tool_timeout_ms

    async def run(
        self,
        *,
        run_id: str,
        thread_id: str,
        agent: AgentRead,
        user_input: str,
        max_steps: int,
        tracer: TraceSink,
    ) -> RunResult:
        started = time.perf_counter()
        policy = StopPolicy(max_steps)
        ctx = RunContext(run_id=run_id, agent_id=agent.id)

        bound_tools = await self._gateway.list_tools(agent_id=agent.id)
        candidates, scores, strategy = await self._select_tools(user_input, bound_tools)

        # Run 级事件统一用 step_no = 0（契约 §3.4）
        await tracer.emit(
            TraceEvent(
                run_id=run_id,
                step_no=0,
                event_type=TraceEventType.RUN_STARTED,
                status=StepStatus.SUCCESS,
                data={
                    "agent_id": agent.id,
                    "input": user_input,
                    "max_steps": max_steps,
                    "model": agent.model,
                },
            )
        )
        await tracer.emit(
            TraceEvent(
                run_id=run_id,
                step_no=0,
                event_type=TraceEventType.TOOL_CANDIDATES,
                status=StepStatus.SUCCESS,
                data={
                    "names": [tool.qualified_name for tool in candidates],
                    "scores": scores,
                    "strategy": strategy,
                    "top_k": self._top_k,
                },
            )
        )

        graph = build_graph(
            model=self._model_factory(agent.model),
            gateway=self._gateway,
            tracer=tracer,
            agent=agent,
            max_steps=max_steps,
            candidates=candidates,
            ctx=ctx,
            tool_timeout_ms=self._tool_timeout_ms,
        )
        initial_state: AgentState = {
            "messages": [HumanMessage(content=user_input)],
            "candidate_tools": candidates,
            "step_count": 0,
            "run_id": run_id,
            "final_answer": None,
        }

        final_state: AgentState = initial_state
        try:
            async for snapshot in graph.astream(
                initial_state,
                config={"configurable": {"thread_id": thread_id}},
                stream_mode="values",
            ):
                final_state = snapshot
        except Exception as exc:
            # 预期内的失败（模型 / 工具）已在节点里转成 stop_reason；能走到这里的是未归类的
            # 内部异常。Run 必须有终态，否则会永远停在 RUNNING，因此记为 INTERNAL_ERROR，
            # 同时把堆栈打到日志（契约 §2.2）。
            logger.exception("Run %s 执行时发生内部异常", run_id)
            ctx.stop_reason = StopReason.INTERNAL_ERROR
            ctx.error_code = "INTERNAL_ERROR"
            ctx.error_message = f"{type(exc).__name__}: {exc}"[:512]

        step_count = int(final_state.get("step_count", 0))
        final_answer = final_state.get("final_answer")
        stop_reason = ctx.stop_reason or StopReason.FINISHED
        status = policy.resolve_status(stop_reason=stop_reason, final_answer=final_answer)
        duration_ms = _elapsed_ms(started)

        # SUCCESS / PARTIAL 视为正常结束（PARTIAL 由 MAX_STEPS 触发，但已带 stop_reason 说明原因）
        finished = status in (RunStatus.SUCCESS, RunStatus.PARTIAL)
        if finished:
            event = TraceEvent(
                run_id=run_id,
                step_no=step_count,
                event_type=TraceEventType.RUN_FINISHED,
                status=StepStatus.SUCCESS,
                duration_ms=duration_ms,
                data={
                    "output": final_answer or "",
                    "stop_reason": stop_reason.value,
                    "llm_calls": ctx.llm_calls,
                    "tool_calls": ctx.tool_calls,
                    "step_count": step_count,
                },
            )
        else:
            event = TraceEvent(
                run_id=run_id,
                step_no=step_count,
                event_type=TraceEventType.RUN_FAILED,
                status=StepStatus.FAILED,
                duration_ms=duration_ms,
                data={
                    "stop_reason": stop_reason.value,
                    "error_code": ctx.error_code,
                    "error_message": ctx.error_message,
                    "partial_output": final_answer,
                },
            )
        await tracer.emit(event)

        return RunResult(
            run_id=run_id,
            status=status,
            stop_reason=stop_reason,
            output=final_answer,
            llm_calls=ctx.llm_calls,
            tool_calls=ctx.tool_calls,
            step_count=step_count,
            duration_ms=duration_ms,
            error_code=ctx.error_code,
            error_message=ctx.error_message,
        )

    async def _select_tools(
        self,
        query: str,
        tools: list[ToolDefinition],
    ) -> tuple[list[ToolDefinition], list[float], str]:
        """返回（候选工具, 对应得分, 策略标识）。

        策略标识用于 TOOL_CANDIDATES 事件；未启用筛选时得分为空数组。
        """
        if self._selector is None:
            return tools, [], "none"
        candidates = await self._selector.select(query, tools, top_k=self._top_k)
        return (
            [candidate.tool for candidate in candidates],
            [candidate.score for candidate in candidates],
            "tfidf",
        )


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
