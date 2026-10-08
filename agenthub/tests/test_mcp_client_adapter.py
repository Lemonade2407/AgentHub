"""Streamable HTTP MCP 客户端单测（设计文档 §8.2 / 契约 §2.6）。

用 `httpx.MockTransport` 离线验证 JSON-RPC 报文、SSE 解析与 session 回带，
不打真实网络。
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.enums import TransportType
from app.mcp.client_adapter import (
    INVALID_ARGUMENT,
    HttpMcpClientFactory,
    McpClientError,
    StreamableHttpMcpClient,
    parse_sse_data,
    select_rpc_message,
)
from tests.mcp_fakes import make_server


def test_parse_sse_data_skips_comments_and_bad_json() -> None:
    text = (
        ": keep-alive\n"
        "\n"
        "event: message\n"
        'data: {"a": 1}\n'
        "\n"
        "data: not-json\n"
        "\n"
        'data: {"b": 2}\n'
        "\n"
    )

    assert parse_sse_data(text) == [{"a": 1}, {"b": 2}]


def test_select_rpc_message() -> None:
    messages = [
        {"jsonrpc": "2.0", "method": "notifications/progress", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}},
    ]

    assert select_rpc_message(messages, 2) == messages[1]
    # 无匹配 id 时退回最后一条带 result / error 的消息
    assert select_rpc_message(messages, 9) == messages[1]
    assert select_rpc_message([{"method": "x"}], 1) is None


def test_unsupported_transport_is_rejected() -> None:
    with pytest.raises(McpClientError) as excinfo:
        StreamableHttpMcpClient(make_server(transport=TransportType.STDIO))

    assert excinfo.value.error_code == INVALID_ARGUMENT


async def test_handshake_list_and_call_over_streamable_http() -> None:
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        method = payload["method"]
        seen.append((method, request.headers.get("mcp-session-id")))
        request_id = payload.get("id")
        if method == "initialize":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"protocolVersion": "2025-06-18", "serverInfo": {"name": "demo"}},
                },
                headers={"mcp-session-id": "sess-1"},
            )
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/list":
            payload_obj = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [
                        {
                            "name": "list_issues",
                            "description": "d",
                            "inputSchema": {"type": "object"},
                            "annotations": {"readOnlyHint": True},
                        }
                    ]
                },
            }
            body = "event: message\ndata: " + json.dumps(payload_obj) + "\n\n"
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        if method == "tools/call":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"content": [{"type": "text", "text": "3 issues"}], "isError": False},
                },
            )
        raise AssertionError(f"未预期的 MCP 方法：{method}")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = StreamableHttpMcpClient(make_server(), http_client=http_client)

    server_info = await client.initialize()
    assert server_info["serverInfo"]["name"] == "demo"

    tools = await client.list_tools()
    assert [tool.name for tool in tools] == ["list_issues"]
    assert tools[0].read_only_hint is True
    assert tools[0].input_schema == {"type": "object"}

    result = await client.call_tool("list_issues", {"state": "open"})
    assert result.is_error is False
    assert result.content == [{"type": "text", "text": "3 issues"}]

    assert [method for method, _ in seen] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
    ]
    # initialize 尚无 session；之后的请求都回带 Mcp-Session-Id
    assert seen[0][1] is None
    assert all(session_id == "sess-1" for _, session_id in seen[1:])

    await http_client.aclose()


async def test_server_headers_are_sent() -> None:
    captured: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["api_key"] = request.headers.get("x-api-key")
        payload = json.loads(request.content)
        if payload["method"] == "notifications/initialized":
            return httpx.Response(202)
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": payload["id"], "result": {"serverInfo": {"name": "demo"}}},
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = StreamableHttpMcpClient(
        make_server(headers={"X-Api-Key": "secret"}), http_client=http_client
    )

    await client.initialize()

    assert captured["api_key"] == "secret"
    await http_client.aclose()


async def test_factory_reuses_and_invalidates_clients() -> None:
    factory = HttpMcpClientFactory()
    server = make_server(id=7)

    first = factory.for_server(server)
    assert factory.for_server(server) is first  # 同一 Server 复用同一客户端

    await factory.invalidate(7)
    second = factory.for_server(server)
    assert second is not first

    await factory.aclose()
