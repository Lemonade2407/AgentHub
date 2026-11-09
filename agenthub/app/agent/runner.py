"""AgentRunner —— Agent 执行入口。设计文档 §6.3 / 契约 §6.2。归属：A（Agent Runtime）。

职责（对应设计文档 §6.3）：
1. 加载 AgentDefinition（由调用方通过 `agent` 传入）；
2. 解析并注入 Skill（V2）：组装最终 system prompt、合并工具、校验参数与依赖；
3. 获取 Agent 已绑定工具；
4. 调用 ToolSelector 得到 Top-K 候选工具；
5. 构建 compiled LangGraph；
6. 使用异步 streaming 执行；
7. 将执行过程映射为 TraceEvent；
8. 在成功 / 超限 / 模型错误 / 工具错误时统一结束 Run。

本模块不依赖 FastAPI、SQLAlchemy 与 Response 对象（设计文档 §3.1），
因此可被 API 层、测试与脚本直接复用。

V2 新增入参均为可选，不传时行为与 V1 完全一致：
- `skills`：D 从 `skill` / `agent_skill` 解析出的 Skill 快照；
- `model_credential`：D 从 `model_api` 解密后传入的凭据；
- 模型凭据必须配合 `ModelGateway` 使用。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.agent.graph import RunContext, build_graph
from app.agent.model_gateway import ModelCredential, ModelErrorCode, ModelGateway, ModelGatewayError
from app.agent.model_provider import build_chat_model
from app.agent.skills import SkillDefinition, SkillPlan, SkillResolver, SkillValidationError
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

    `model_gateway` 与 `model_credential` 同时存在时走 V2 的用户级模型链路；
    否则回落到 `model_factory(agent.model)`（V1 环境变量方案）。
    """

    def __init__(
        self,
        *,
        gateway: McpToolGateway,
        tool_selector: ToolSelector | None = None,
        model_factory: Callable[[str], BaseChatModel] = build_chat_model,
        model_gateway: ModelGateway | None = None,
        skill_resolver: SkillResolver | None = None,
        top_k: int = DEFAULT_TOP_K,
        tool_timeout_ms: int = DEFAULT_TOOL_TIMEOUT_MS,
    ) -> None:
        self._gateway = gateway
        self._selector = tool_selector
        self._model_factory = model_factory
        self._model_gateway = model_gateway
        self._skill_resolver = skill_resolver or SkillResolver()
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
        skills: Sequence[SkillDefinition] = (),
        model_credential: ModelCredential | None = None,
    ) -> RunResult:
        started = time.perf_counter()
        policy = StopPolicy(max_steps)
        ctx = RunContext(run_id=run_id, agent_id=agent.id)
        model_meta = _model_meta(agent, model_credential)

        bound_tools = await self._gateway.list_tools(agent_id=agent.id)
        try:
            plan = self._skill_resolver.resolve(
                agent_system_prompt=agent.system_prompt,
                skills=skills,
                bound_tools=bound_tools,
                prompt_budget_chars=SkillResolver.budget_from_context_window(
                    model_credential.context_window if model_credential else None
                )
                if model_credential
                else None,
            )
        except SkillValidationError as exc:
            # 参数契约不满足属于 Agent 定义问题：Run 必须有终态，错误码用于前端给出修复指引
            return await self._fail(
                run_id=run_id,
                tracer=tracer,
                stop_reason=StopReason.MODEL_ERROR,
                error_code=exc.code,
                error_message=_skill_error_message(exc),
                started=started,
            )

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
                    **model_meta,
                    "skills": [item.slug for item in plan.injected],
                    "skill_warnings": plan.warnings,
                },
            )
        )
        await self._emit_skill_events(run_id=run_id, plan=plan, tracer=tracer)

        if plan.missing_required_tools:
            missing = plan.missing_required_tools
            return await self._fail(
                run_id=run_id,
                tracer=tracer,
                stop_reason=StopReason.TOOL_ERROR,
                error_code="SKILL_TOOL_MISSING",
                error_message=(
                    "Skill 依赖的 Tool 不可用："
                    + ", ".join(f"{item.skill_slug}->{item.qualified_name}" for item in missing)
                ),
                started=started,
            )

        candidates, scores, strategy = await self._select_tools(user_input, plan.tools)
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
                    "skills": [item.slug for item in plan.injected],
                },
            )
        )

        try:
            model = self._build_model(
                agent,
                model_credential,
                require_tool_call=bool(plan.tools),
            )
        except ModelGatewayError as exc:
            return await self._fail(
                run_id=run_id,
                tracer=tracer,
                stop_reason=StopReason.MODEL_ERROR,
                error_code=exc.code,
                error_message=exc.message,
                started=started,
            )

        graph = build_graph(
            model=model,
            gateway=self._gateway,
            tracer=tracer,
            agent=agent.model_copy(update={"system_prompt": plan.system_prompt}),
            max_steps=max_steps,
            candidates=candidates,
            ctx=ctx,
            tool_timeout_ms=self._tool_timeout_ms,
            model_meta=model_meta,
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
                    **model_meta,
                    "skills": [item.slug for item in plan.injected],
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

    def _build_model(
        self,
        agent: AgentRead,
        credential: ModelCredential | None,
        *,
        require_tool_call: bool,
    ) -> BaseChatModel:
        if credential is None:
            return self._model_factory(agent.model)
        if self._model_gateway is None:
            raise ModelGatewayError(
                ModelErrorCode.CONFIG,
                "传入 model_credential 时必须为 AgentRunner 配置 ModelGateway",
            )
        return self._model_gateway.build(credential, require_tool_call=require_tool_call)

    async def _emit_skill_events(
        self,
        *,
        run_id: str,
        plan: SkillPlan,
        tracer: TraceSink,
    ) -> None:
        for item in plan.injected:
            await tracer.emit(
                TraceEvent(
                    run_id=run_id,
                    step_no=0,
                    event_type=TraceEventType.SKILL_INJECTED,
                    status=StepStatus.SUCCESS,
                    data={
                        "skill_id": item.skill_id,
                        "slug": item.slug,
                        "name": item.name,
                        "version": item.version,
                        "order_no": item.order_no,
                        "prompt_chars": item.prompt_chars,
                        "tools": item.tools,
                    },
                )
            )
        for missing in plan.missing_tools:
            await tracer.emit(
                TraceEvent(
                    run_id=run_id,
                    step_no=0,
                    event_type=TraceEventType.SKILL_TOOL_MISSING,
                    status=StepStatus.SKIPPED if not missing.required else StepStatus.FAILED,
                    data={
                        "skill_slug": missing.skill_slug,
                        "tool": missing.qualified_name,
                        "required": missing.required,
                    },
                )
            )

    async def _fail(
        self,
        *,
        run_id: str,
        tracer: TraceSink,
        stop_reason: StopReason,
        error_code: str,
        error_message: str,
        started: float,
    ) -> RunResult:
        """运行前置失败（Skill 参数 / 工具依赖 / 模型配置）：发 RUN_FAILED 并返回终态。"""
        duration_ms = _elapsed_ms(started)
        await tracer.emit(
            TraceEvent(
                run_id=run_id,
                step_no=0,
                event_type=TraceEventType.RUN_FAILED,
                status=StepStatus.FAILED,
                duration_ms=duration_ms,
                data={
                    "stop_reason": stop_reason.value,
                    "error_code": error_code,
                    "error_message": error_message,
                    "partial_output": None,
                },
            )
        )
        return RunResult(
            run_id=run_id,
            status=RunStatus.FAILED,
            stop_reason=stop_reason,
            output=None,
            llm_calls=0,
            tool_calls=0,
            step_count=0,
            duration_ms=duration_ms,
            error_code=error_code,
            error_message=error_message,
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


def _model_meta(agent: AgentRead, credential: ModelCredential | None) -> dict[str, object]:
    """Trace 中的模型标识：V2 走凭据信息，V1 退化为 `agent.model`。"""
    if credential is not None:
        return credential.trace_meta()
    return {"model": agent.model}


def _skill_error_message(exc: SkillValidationError) -> str:
    parts = [exc.message]
    if exc.param:
        parts.append(f"参数：{exc.param}")
    if exc.skill_slug:
        parts.append(f"Skill：{exc.skill_slug}")
    return "；".join(parts)[:512]


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
