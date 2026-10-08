"""Demo MCP Server 集成测试（设计文档 §17「MCP 集成」、契约 §9.1/§9.2）。

在本地起一个真实的 Demo MCP Server，用 B 自己的 `StreamableHttpMcpClient` /
`DiscoveryService` / `ToolRouter` 打通「Discovery → call_tool → 错误 / 超时」链路。
"""

from __future__ import annotations

import threading

import pytest

from app.core.enums import RiskLevel
from app.mcp.client_adapter import (
    HttpMcpClientFactory,
    McpClientError,
    StreamableHttpMcpClient,
)
from app.mcp.discovery import DiscoveryService
from app.mcp.router import ToolRouter
from app.mcp.schemas import ToolCall, ToolContext
from app.tools.registry import InMemoryToolRegistry
from demo_mcp_server.server import build_server
from tests.mcp_fakes import (
    FakeServerProvider,
    InMemoryToolRegistryStore,
    RecordingServerStore,
    make_server,
    make_tool,
)

RUN_ID = "r_7f3a91c2b4e0"
AGENT_ID = 1
DEMO_SERVER_ID = 1


@pytest.fixture
def demo_endpoint() -> str:
    """在随机端口启动 Demo MCP Server，测试结束即关闭。"""
    server = build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/mcp"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def demo_server_config(endpoint: str):
    return make_server(id=DEMO_SERVER_ID, name="demo", endpoint=endpoint)


async def test_tools_list_exposes_demo_tools(demo_endpoint: str) -> None:
    async with StreamableHttpMcpClient(demo_server_config(demo_endpoint)) as client:
        tools = await client.list_tools()

    assert [tool.name for tool in tools] == [
        "list_issues",
        "search_web",
        "read_broken_report",
        "query_slow_data",
    ]
    # 全部为合法 object schema，Discovery 才会入库并置 enabled=true
    assert all(tool.input_schema.get("type") == "object" for tool in tools)


async def test_discovery_end_to_end(demo_endpoint: str) -> None:
    store = InMemoryToolRegistryStore()
    server_store = RecordingServerStore()
    factory = HttpMcpClientFactory()
    service = DiscoveryService(
        registry_store=store,
        server_store=server_store,
        client_factory=factory,
    )

    result = await service.discover(demo_server_config(demo_endpoint))
    await factory.aclose()

    assert (result.added, result.updated, result.removed, result.total) == (4, 0, 0, 4)
    assert store.tools[(DEMO_SERVER_ID, "search_web")].qualified_name == "demo.search_web"
    assert store.tools[(DEMO_SERVER_ID, "list_issues")].risk_level is RiskLevel.READ_ONLY
    assert all(tool.enabled for tool in store.tools.values())


async def test_call_tool_success(demo_endpoint: str) -> None:
    async with StreamableHttpMcpClient(demo_server_config(demo_endpoint)) as client:
        result = await client.call_tool("search_web", {"q": "agenthub"})

    assert result.is_error is False
    assert "agenthub" in result.content[0]["text"]


async def test_call_tool_error_is_reported(demo_endpoint: str) -> None:
    async with StreamableHttpMcpClient(demo_server_config(demo_endpoint)) as client:
        result = await client.call_tool("read_broken_report", {"path": "/reports/x.csv"})

    assert result.is_error is True
    assert "无法读取" in result.content[0]["text"]


async def test_unknown_tool_raises_client_error(demo_endpoint: str) -> None:
    async with StreamableHttpMcpClient(demo_server_config(demo_endpoint)) as client:
        with pytest.raises(McpClientError):
            await client.call_tool("nope_missing", {})


async def test_router_executes_tool_end_to_end(demo_endpoint: str) -> None:
    """完整链路：Schema 校验 → 真实 MCP 调用 → Observation 文本。"""
    tool = make_tool(
        "demo.list_issues",
        id=11,
        server_id=DEMO_SERVER_ID,
        input_schema={
            "type": "object",
            "properties": {"state": {"type": "string", "enum": ["open", "closed"]}},
        },
    )
    factory = HttpMcpClientFactory()
    router = _make_router([tool], demo_endpoint, factory)

    result = await router.execute_tool(
        ToolCall(call_id="c1", qualified_name="demo.list_issues", arguments={"state": "open"}),
        _context(timeout_ms=5_000),
    )
    await factory.aclose()

    assert result.ok is True
    assert "Found 3 issues" in result.text


async def test_router_maps_slow_tool_to_timeout(demo_endpoint: str) -> None:
    tool = make_tool(
        "demo.query_slow_data",
        id=11,
        server_id=DEMO_SERVER_ID,
        input_schema={"type": "object", "properties": {"seconds": {"type": "number"}}},
    )
    factory = HttpMcpClientFactory()
    router = _make_router([tool], demo_endpoint, factory)

    result = await router.execute_tool(
        ToolCall(
            call_id="c1",
            qualified_name="demo.query_slow_data",
            arguments={"seconds": 1},
        ),
        _context(timeout_ms=50),
    )
    await factory.aclose()

    assert result.ok is False
    assert result.error_code == "TOOL_TIMEOUT"


def _make_router(tools, endpoint: str, factory: HttpMcpClientFactory) -> ToolRouter:
    return ToolRouter(
        registry=InMemoryToolRegistry(
            tools=tools, bindings={AGENT_ID: {tool.id for tool in tools}}
        ),
        servers=FakeServerProvider([demo_server_config(endpoint)]),
        client_factory=factory,
    )


def _context(*, timeout_ms: int) -> ToolContext:
    return ToolContext(run_id=RUN_ID, agent_id=AGENT_ID, step_no=2, timeout_ms=timeout_ms)
