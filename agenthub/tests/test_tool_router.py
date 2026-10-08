"""Tool Router 单测（设计文档 §8.3 / 契约 §6.1）。

覆盖：绑定过滤、成功执行、以及 6 类失败路径（TOOL_NOT_FOUND / TOOL_NOT_BOUND /
TOOL_RISK_DENIED / TOOL_SCHEMA_INVALID / TOOL_TIMEOUT / MCP_SERVER_UNREACHABLE）。
"""

from __future__ import annotations

from app.core.enums import RiskLevel
from app.mcp.client_adapter import (
    MCP_SERVER_UNREACHABLE,
    TOOL_TIMEOUT,
    McpCallResult,
    McpClientError,
)
from app.mcp.gateway import McpToolGateway
from app.mcp.router import ToolRouter, validate_arguments
from app.mcp.schemas import ToolCall, ToolContext
from app.tools.registry import InMemoryToolRegistry, ToolRegistry
from tests.mcp_fakes import (
    FakeMcpClient,
    FakeMcpClientFactory,
    FakeServerProvider,
    make_server,
    make_tool,
)

RUN_ID = "r_7f3a91c2b4e0"
AGENT_ID = 1
GITHUB_TOOL = "github.list_issues"


def make_context(*, timeout_ms: int = 30_000) -> ToolContext:
    return ToolContext(run_id=RUN_ID, agent_id=AGENT_ID, step_no=2, timeout_ms=timeout_ms)


def make_call(qualified_name: str = GITHUB_TOOL, arguments: dict | None = None) -> ToolCall:
    return ToolCall(call_id="call_1", qualified_name=qualified_name, arguments=arguments or {})


def make_router(
    tools,
    client: FakeMcpClient,
    *,
    bindings: dict[int, set[int]] | None = None,
    servers=None,
) -> ToolRouter:
    registry = InMemoryToolRegistry(
        tools=tools,
        bindings=bindings if bindings is not None else {AGENT_ID: {tool.id for tool in tools}},
    )
    return ToolRouter(
        registry=registry,
        servers=FakeServerProvider(servers if servers is not None else [make_server()]),
        client_factory=FakeMcpClientFactory(client),
    )


async def test_list_tools_returns_bound_and_enabled() -> None:
    enabled = make_tool(GITHUB_TOOL, id=11)
    disabled = make_tool("search.search_web", id=12, enabled=False)
    router = make_router([enabled, disabled], FakeMcpClient())

    tools = await router.list_tools(agent_id=AGENT_ID)

    assert [tool.qualified_name for tool in tools] == [GITHUB_TOOL]
    assert isinstance(router, McpToolGateway)
    assert isinstance(InMemoryToolRegistry(), ToolRegistry)


async def test_execute_tool_success() -> None:
    client = FakeMcpClient(
        results={
            "list_issues": McpCallResult(
                content=[{"type": "text", "text": "Found 3 issues"}],
            )
        }
    )
    router = make_router([make_tool(GITHUB_TOOL, id=11)], client)

    result = await router.execute_tool(make_call(arguments={"state": "open"}), make_context())

    assert result.ok is True
    assert result.error_code is None
    assert result.text == "Found 3 issues"
    assert result.call_id == "call_1"
    assert result.duration_ms >= 0
    # Router 把 qualified_name 还原为 remote_name 再调用 MCP
    assert client.call_arguments == [("list_issues", {"state": "open"})]


async def test_unknown_tool_returns_tool_not_found() -> None:
    client = FakeMcpClient()
    router = make_router([make_tool(GITHUB_TOOL, id=11)], client)

    result = await router.execute_tool(make_call("nope.missing"), make_context())

    assert result.ok is False
    assert result.error_code == "TOOL_NOT_FOUND"
    assert client.call_arguments == []


async def test_unbound_tool_returns_tool_not_bound() -> None:
    client = FakeMcpClient()
    router = make_router([make_tool(GITHUB_TOOL, id=11)], client, bindings={AGENT_ID: set()})

    result = await router.execute_tool(make_call(), make_context())

    assert result.ok is False
    assert result.error_code == "TOOL_NOT_BOUND"
    assert client.call_arguments == []


async def test_write_tool_is_denied_without_calling_client() -> None:
    client = FakeMcpClient()
    tool = make_tool(GITHUB_TOOL, id=11, risk_level=RiskLevel.WRITE)
    router = make_router([tool], client)

    result = await router.execute_tool(make_call(), make_context())

    assert result.ok is False
    assert result.error_code == "TOOL_RISK_DENIED"
    assert client.call_arguments == []


async def test_schema_violation_returns_tool_schema_invalid() -> None:
    client = FakeMcpClient()
    tool = make_tool(
        GITHUB_TOOL,
        id=11,
        input_schema={
            "type": "object",
            "properties": {"state": {"type": "string"}},
            "required": ["state"],
        },
    )
    router = make_router([tool], client)

    result = await router.execute_tool(make_call(arguments={"state": 1}), make_context())

    assert result.ok is False
    assert result.error_code == "TOOL_SCHEMA_INVALID"
    assert client.call_arguments == []


async def test_mcp_is_error_is_returned_as_tool_execution_failed() -> None:
    client = FakeMcpClient(
        results={
            "list_issues": McpCallResult(
                content=[{"type": "text", "text": "boom"}], is_error=True
            )
        }
    )
    router = make_router([make_tool(GITHUB_TOOL, id=11)], client)

    result = await router.execute_tool(make_call(), make_context())

    assert result.ok is False
    assert result.error_code == "TOOL_EXECUTION_FAILED"
    assert result.text == "boom"


async def test_slow_tool_is_mapped_to_tool_timeout() -> None:
    client = FakeMcpClient(delay_s=0.05)
    router = make_router([make_tool(GITHUB_TOOL, id=11)], client)

    result = await router.execute_tool(make_call(), make_context(timeout_ms=10))

    assert result.ok is False
    assert result.error_code == TOOL_TIMEOUT
    assert "timed out" in (result.error_message or "")


async def test_client_error_is_propagated_by_error_code() -> None:
    client = FakeMcpClient(call_error=McpClientError(MCP_SERVER_UNREACHABLE, "connection refused"))
    router = make_router([make_tool(GITHUB_TOOL, id=11)], client)

    result = await router.execute_tool(make_call(), make_context())

    assert result.ok is False
    assert result.error_code == MCP_SERVER_UNREACHABLE


async def test_missing_server_returns_unreachable() -> None:
    client = FakeMcpClient()
    router = make_router([make_tool(GITHUB_TOOL, id=11)], client, servers=[])

    result = await router.execute_tool(make_call(), make_context())

    assert result.ok is False
    assert result.error_code == MCP_SERVER_UNREACHABLE
    assert client.call_arguments == []


async def test_oversized_content_is_trimmed_but_text_kept() -> None:
    """契约 §7 体积截断：content 超过 64 KB 时丢弃，只保留 text。"""
    huge = "x" * 70_000
    client = FakeMcpClient(results={"list_issues": McpCallResult(content=[{"type": "text", "text": huge}])})
    router = make_router([make_tool(GITHUB_TOOL, id=11)], client)

    result = await router.execute_tool(make_call(), make_context())

    assert result.ok is True
    assert result.content == []
    assert result.text == huge


def test_validate_arguments_cases() -> None:
    schema = {
        "type": "object",
        "properties": {
            "state": {"type": "string", "enum": ["open", "closed"]},
            "labels": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["state"],
        "additionalProperties": False,
    }

    assert validate_arguments(schema, {"state": "open", "labels": ["bug"]}) is None
    assert validate_arguments({}, {"anything": 1}) is None
    assert "必填" in (validate_arguments(schema, {}) or "")
    assert "enum" in (validate_arguments(schema, {"state": "unknown"}) or "")
    assert "期望 string" in (validate_arguments(schema, {"state": 1}) or "")
    assert "labels[0]" in (validate_arguments(schema, {"state": "open", "labels": [1]}) or "")
    assert "未定义字段" in (validate_arguments(schema, {"state": "open", "extra": 1}) or "")
