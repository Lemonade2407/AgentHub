"""AgentRunner 集成测试（设计文档 §17：无 Tool / 单 Tool / 多 Tool / max_steps）。

用 `ScriptedChatModel` 替代真实 LLM，验证图执行、Trace 事件与 RunResult 的一致性。
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, ToolMessage

from app.agent.graph import RESULT_SUMMARY_LIMIT
from app.agent.runner import AgentRunner, RunResult
from app.core.enums import RunStatus, StepStatus, StopReason, TraceEventType
from app.mcp.schemas import ToolResult
from app.schemas.agent import AgentRead
from tests.fakes import (
    ExplodingGateway,
    FakeGateway,
    FakeSelector,
    FakeTracer,
    ModelBoom,
    ScriptedChatModel,
    make_agent,
    make_tool,
)

RUN_ID = "r_7f3a91c2b4e0"
THREAD_ID = "t_11a2b3c4d5e6"

SEARCH_TOOL = "search.search_web"
GITHUB_TOOL = "github.list_issues"


def tool_call(name: str, args: dict | None = None, call_id: str = "call_1") -> AIMessage:
    """构造一次工具调用响应。`name` 必须是模型可见的编码名（`.` -> `__`）。"""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args or {}, "id": call_id}],
    )


def make_runner(
    gateway: FakeGateway,
    model: ScriptedChatModel,
    selector: FakeSelector | None = None,
) -> AgentRunner:
    return AgentRunner(
        gateway=gateway,
        tool_selector=selector,
        model_factory=lambda _model: model,
    )


async def run_agent(
    gateway: FakeGateway,
    model: ScriptedChatModel,
    tracer: FakeTracer,
    *,
    selector: FakeSelector | None = None,
    agent: AgentRead | None = None,
    user_input: str = "问题",
    max_steps: int = 8,
) -> RunResult:
    return await make_runner(gateway, model, selector).run(
        run_id=RUN_ID,
        thread_id=THREAD_ID,
        agent=agent or make_agent(),
        user_input=user_input,
        max_steps=max_steps,
        tracer=tracer,
    )


async def test_run_without_tools_finishes_immediately() -> None:
    """无 Tool：模型直接给出答案，一次 LLM 调用结束。"""
    model = ScriptedChatModel(script=[AIMessage(content="你好，我是研究员。")])
    gateway = FakeGateway(tools=[])
    tracer = FakeTracer()

    result = await run_agent(gateway, model, tracer, agent=make_agent(tool_ids=[]), user_input="你好")

    assert result.status is RunStatus.SUCCESS
    assert result.stop_reason is StopReason.FINISHED
    assert result.output == "你好，我是研究员。"
    assert (result.llm_calls, result.tool_calls, result.step_count) == (1, 0, 1)
    assert model.bound_tools == []  # 没有候选工具时不应 bind_tools
    assert gateway.calls == []
    assert tracer.types() == [
        TraceEventType.RUN_STARTED,
        TraceEventType.TOOL_CANDIDATES,
        TraceEventType.LLM_STARTED,
        TraceEventType.LLM_FINISHED,
        TraceEventType.STATE_UPDATED,
        TraceEventType.RUN_FINISHED,
    ]


async def test_run_with_single_tool_call() -> None:
    """单 Tool：LLM -> Tool -> LLM 三步，Observation 回填给模型。"""
    model = ScriptedChatModel(
        script=[
            tool_call("search__search_web", {"q": "agenthub"}),
            AIMessage(content="找到了 3 条结果。"),
        ]
    )
    gateway = FakeGateway(tools=[make_tool(SEARCH_TOOL)], default_text="1. AgentHub 仓库")
    tracer = FakeTracer()

    result = await run_agent(gateway, model, tracer, user_input="查一下 agenthub")

    assert result.status is RunStatus.SUCCESS
    assert result.stop_reason is StopReason.FINISHED
    assert result.output == "找到了 3 条结果。"
    assert (result.llm_calls, result.tool_calls, result.step_count) == (2, 1, 3)

    # 暴露给模型的是编码名，契约里的 qualified_name 不受影响
    assert [tool["function"]["name"] for tool in model.bound_tools] == ["search__search_web"]
    assert gateway.calls[0].qualified_name == SEARCH_TOOL
    assert gateway.calls[0].arguments == {"q": "agenthub"}

    # Observation 已回填，且 tool_call_id 与模型请求一致
    observation = model.calls[1][-1]
    assert isinstance(observation, ToolMessage)
    assert observation.tool_call_id == "call_1"
    assert "AgentHub 仓库" in observation.content


async def test_step_no_follows_graph_execution_steps() -> None:
    """契约 §3.4 / §5.5：step_no 为图执行步序号，同一节点执行内的事件共享同一值。"""
    model = ScriptedChatModel(script=[tool_call("search__search_web"), AIMessage(content="答案")])
    gateway = FakeGateway(tools=[make_tool(SEARCH_TOOL)])
    tracer = FakeTracer()

    result = await run_agent(gateway, model, tracer)

    assert tracer.step_nos(TraceEventType.RUN_STARTED) == [0]
    assert tracer.step_nos(TraceEventType.TOOL_CANDIDATES) == [0]
    assert tracer.step_nos(TraceEventType.LLM_STARTED) == [1, 3]
    assert tracer.step_nos(TraceEventType.LLM_FINISHED) == [1, 3]
    assert tracer.step_nos(TraceEventType.TOOL_CALL_STARTED) == [2]
    assert tracer.step_nos(TraceEventType.TOOL_CALL_FINISHED) == [2]
    assert tracer.step_nos(TraceEventType.STATE_UPDATED) == [1, 2, 3]
    # RUN_FINISHED 与最后一步同号
    assert tracer.step_nos(TraceEventType.RUN_FINISHED) == [result.step_count] == [3]
    assert {event.run_id for event in tracer.events} == {RUN_ID}


async def test_run_with_multiple_tool_calls_in_one_step() -> None:
    """多 Tool：一次模型响应里并发两个 tool_call，共享同一 step_no。"""
    model = ScriptedChatModel(
        script=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "github__list_issues", "args": {"state": "open"}, "id": "c1"},
                    {"name": "search__search_web", "args": {"q": "x"}, "id": "c2"},
                ],
            ),
            AIMessage(content="完成。"),
        ]
    )
    gateway = FakeGateway(tools=[make_tool(GITHUB_TOOL), make_tool(SEARCH_TOOL)])
    tracer = FakeTracer()

    result = await run_agent(gateway, model, tracer, user_input="查 issue 并搜索")

    assert (result.llm_calls, result.tool_calls, result.step_count) == (2, 2, 3)
    assert tracer.step_nos(TraceEventType.TOOL_CALL_STARTED) == [2, 2]
    assert [call.qualified_name for call in gateway.calls] == [GITHUB_TOOL, SEARCH_TOOL]
    assert set(tracer.tool_names()) == {GITHUB_TOOL, SEARCH_TOOL}

    observations = [m for m in model.calls[1] if isinstance(m, ToolMessage)]
    assert {m.tool_call_id for m in observations} == {"c1", "c2"}


async def test_max_steps_is_a_hard_bound() -> None:
    """模型始终要求调用工具时，节点执行次数不会超过 max_steps。"""
    model = ScriptedChatModel(
        script=[tool_call("search__search_web", call_id=f"c{i}") for i in range(10)]
    )
    gateway = FakeGateway(tools=[make_tool(SEARCH_TOOL)])
    tracer = FakeTracer()

    result = await run_agent(gateway, model, tracer, user_input="无限循环", max_steps=3)

    assert result.stop_reason is StopReason.MAX_STEPS
    assert result.status is RunStatus.FAILED  # 未产出任何文本
    assert result.output is None
    assert result.step_count == 3
    # step1=model, step2=tools, step3=model（该步的 tool_calls 因预算耗尽未执行）
    assert (result.llm_calls, result.tool_calls) == (2, 1)
    assert tracer.types()[-1] is TraceEventType.RUN_FAILED

    failed_event = tracer.of(TraceEventType.RUN_FAILED)[0]
    assert failed_event.data["stop_reason"] == StopReason.MAX_STEPS.value
    assert failed_event.data["partial_output"] is None


async def test_finish_on_last_allowed_step_is_success_not_max_steps() -> None:
    """刚好用满预算但已给出答案，应判定为 FINISHED，而不是 MAX_STEPS。"""
    model = ScriptedChatModel(script=[tool_call("search__search_web"), AIMessage(content="最终答案")])
    gateway = FakeGateway(tools=[make_tool(SEARCH_TOOL)])
    tracer = FakeTracer()

    result = await run_agent(gateway, model, tracer, max_steps=3)

    assert result.stop_reason is StopReason.FINISHED
    assert result.status is RunStatus.SUCCESS
    assert result.step_count == 3


async def test_max_steps_with_partial_output_is_partial() -> None:
    """模型在请求工具的同时给出了文本：预算耗尽时判定为 PARTIAL 并保留部分产出。"""
    model = ScriptedChatModel(
        script=[
            AIMessage(
                content="已查到 3 条 issue，",
                tool_calls=[{"name": "search__search_web", "args": {}, "id": f"c{i}"}],
            )
            for i in range(5)
        ]
    )
    gateway = FakeGateway(tools=[make_tool(SEARCH_TOOL)])
    tracer = FakeTracer()

    result = await run_agent(gateway, model, tracer, max_steps=3)

    assert result.stop_reason is StopReason.MAX_STEPS
    assert result.status is RunStatus.PARTIAL
    assert result.output == "已查到 3 条 issue，"
    assert result.step_count == 3
    # PARTIAL 属于正常结束，事件仍是 RUN_FINISHED，由 stop_reason 说明原因（契约 §5.4）
    assert tracer.types()[-1] is TraceEventType.RUN_FINISHED
    assert tracer.of(TraceEventType.RUN_FINISHED)[0].data["stop_reason"] == (
        StopReason.MAX_STEPS.value
    )


async def test_model_error_marks_run_failed() -> None:
    model = ScriptedChatModel(script=[ModelBoom("connection reset")])
    gateway = FakeGateway(tools=[make_tool(SEARCH_TOOL)])
    tracer = FakeTracer()

    result = await run_agent(gateway, model, tracer)

    assert result.status is RunStatus.FAILED
    assert result.stop_reason is StopReason.MODEL_ERROR
    assert result.error_code == "MODEL_ERROR"
    assert "connection reset" in (result.error_message or "")
    assert (result.llm_calls, result.tool_calls, result.step_count) == (1, 0, 1)

    llm_finished = tracer.of(TraceEventType.LLM_FINISHED)[0]
    assert llm_finished.status is StepStatus.FAILED
    assert tracer.types()[-1] is TraceEventType.RUN_FAILED


async def test_tool_error_stops_the_run() -> None:
    model = ScriptedChatModel(script=[tool_call("search__search_web")])
    gateway = FakeGateway(
        tools=[make_tool(SEARCH_TOOL)],
        results={
            SEARCH_TOOL: ToolResult(
                call_id="",
                qualified_name=SEARCH_TOOL,
                ok=False,
                error_code="TOOL_TIMEOUT",
                error_message="MCP tool call timed out after 30000ms",
            )
        },
    )
    tracer = FakeTracer()

    result = await run_agent(gateway, model, tracer)

    assert result.status is RunStatus.FAILED
    assert result.stop_reason is StopReason.TOOL_ERROR
    assert result.error_code == "TOOL_TIMEOUT"
    assert (result.llm_calls, result.tool_calls, result.step_count) == (1, 1, 2)

    finished = tracer.of(TraceEventType.TOOL_CALL_FINISHED)[0]
    assert finished.status is StepStatus.FAILED
    assert finished.data["error"]["code"] == "TOOL_TIMEOUT"
    # 工具失败后不再调用模型（设计文档 §6.4：失败且策略不继续）
    assert len(model.calls) == 1


async def test_unknown_tool_name_is_reported_as_tool_not_found() -> None:
    """模型请求未绑定的 Tool 时，记为一次失败调用而不是抛异常。"""
    model = ScriptedChatModel(script=[tool_call("nope__missing")])
    gateway = FakeGateway(tools=[make_tool(SEARCH_TOOL)])
    tracer = FakeTracer()

    result = await run_agent(gateway, model, tracer)

    assert result.stop_reason is StopReason.TOOL_ERROR
    assert result.error_code == "TOOL_NOT_FOUND"
    assert gateway.calls == []


async def test_unexpected_exception_becomes_internal_error(caplog) -> None:
    """违反契约、直接抛异常的实现：Run 仍须有终态，记为 INTERNAL_ERROR 并打日志。"""
    model = ScriptedChatModel(script=[tool_call("search__search_web")])
    gateway = ExplodingGateway(tools=[make_tool(SEARCH_TOOL)])
    tracer = FakeTracer()

    with caplog.at_level(logging.ERROR, logger="app.agent.runner"):
        result = await run_agent(gateway, model, tracer)

    assert result.status is RunStatus.FAILED
    assert result.stop_reason is StopReason.INTERNAL_ERROR
    assert result.error_code == "INTERNAL_ERROR"
    assert "gateway 内部错误" in (result.error_message or "")
    assert tracer.types()[-1] is TraceEventType.RUN_FAILED
    assert "内部异常" in caplog.text


async def test_tool_selector_limits_bound_tools_and_reports_scores() -> None:
    """动态 Tool Selection 生效时，只把候选工具注入模型，并上报得分。"""
    tools = [make_tool(GITHUB_TOOL), make_tool(SEARCH_TOOL), make_tool("db.query")]
    selector = FakeSelector(picks=[GITHUB_TOOL, SEARCH_TOOL], scores={GITHUB_TOOL: 0.81, SEARCH_TOOL: 0.42})
    model = ScriptedChatModel(script=[AIMessage(content="ok")])
    tracer = FakeTracer()

    result = await run_agent(
        FakeGateway(tools=tools), model, tracer, selector=selector, user_input="查 issue"
    )

    assert result.status is RunStatus.SUCCESS
    assert selector.queries == ["查 issue"]
    assert [tool["function"]["name"] for tool in model.bound_tools] == [
        "github__list_issues",
        "search__search_web",
    ]

    candidates = tracer.of(TraceEventType.TOOL_CANDIDATES)[0]
    assert candidates.data["names"] == [GITHUB_TOOL, SEARCH_TOOL]
    assert candidates.data["scores"] == [0.81, 0.42]
    assert candidates.data["strategy"] == "tfidf"


async def test_without_selector_all_bound_tools_are_exposed() -> None:
    tools = [make_tool(GITHUB_TOOL), make_tool(SEARCH_TOOL)]
    model = ScriptedChatModel(script=[AIMessage(content="ok")])
    tracer = FakeTracer()

    await run_agent(FakeGateway(tools=tools), model, tracer)

    assert [tool["function"]["name"] for tool in model.bound_tools] == [
        "github__list_issues",
        "search__search_web",
    ]
    candidates = tracer.of(TraceEventType.TOOL_CANDIDATES)[0]
    assert candidates.data["strategy"] == "none"
    assert candidates.data["scores"] == []


async def test_llm_finished_carries_token_usage_and_finish_reason() -> None:
    message = AIMessage(
        content="ok",
        usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
        response_metadata={"finish_reason": "stop"},
    )
    tracer = FakeTracer()

    await run_agent(FakeGateway(tools=[]), ScriptedChatModel(script=[message]), tracer, agent=make_agent(tool_ids=[]))

    finished = tracer.of(TraceEventType.LLM_FINISHED)[0]
    assert finished.data["token_usage"] == {"prompt": 10, "completion": 4, "total": 14}
    assert finished.data["finish_reason"] == "stop"
    assert finished.data["tool_call_count"] == 0


async def test_tool_result_summary_is_truncated_in_trace() -> None:
    model = ScriptedChatModel(script=[tool_call("search__search_web"), AIMessage(content="ok")])
    gateway = FakeGateway(tools=[make_tool(SEARCH_TOOL)], default_text="x" * 3000)
    tracer = FakeTracer()

    await run_agent(gateway, model, tracer)

    finished = tracer.of(TraceEventType.TOOL_CALL_FINISHED)[0]
    assert finished.data["truncated"] is True
    assert len(finished.data["result_summary"]) == RESULT_SUMMARY_LIMIT
    assert finished.data["result_bytes"] == 3000
