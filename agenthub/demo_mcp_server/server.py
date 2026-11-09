"""Demo MCP Server —— B（MCP Hub）用于真实 MCP 集成测试的对端（契约 §9.1）。

提供 4 个只读 Tool，覆盖 Discovery / call_tool 的**成功、报错、超时**三条路径：

| Tool | 路径 |
|---|---|
| `list_issues` | 成功（模拟 GitHub issue 列表） |
| `search_web` | 成功（模拟搜索结果） |
| `read_broken_report` | 报错（`isError=true`） |
| `query_slow_data` | 超时（默认 sleep 35s，超过 Tool Call 默认 30s 超时） |

传输：`streamable_http`（契约 §2.6 的 V1 唯一支持），单个端点 `POST /mcp`，
JSON-RPC 2.0 报文，响应 `application/json`。实现只用标准库（不新增依赖），
因此可被 D 直接放进 `docker-compose` 的 `demo-mcp` 服务（设计文档 §18）。

本地启动（默认 `0.0.0.0:8100`）::

    python -m demo_mcp_server --host 0.0.0.0 --port 8100

平台侧按契约 §4.2.1 手动注册，`endpoint = http://demo-mcp:8100/mcp`；
**不自动注册**（契约 §10 D5）。
"""

from __future__ import annotations

import argparse
import json
import logging
import time
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import urlparse

logger = logging.getLogger("demo_mcp_server")

MCP_PATH = "/mcp"
PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "agenthub-demo-mcp", "version": "0.1.0"}

# 超时演示 Tool 的默认 sleep 秒数：大于 Tool Call 默认超时 30s（契约 §6.1）
DEFAULT_SLOW_SECONDS = 35.0

ToolHandler = Callable[[dict], tuple[list[dict], bool]]


@dataclass(frozen=True)
class DemoTool:
    """一个 Demo Tool：元数据 + 处理函数。

    处理函数返回 `(content, is_error)`，`content` 为 MCP content 数组。
    """

    name: str
    description: str
    input_schema: dict
    handler: ToolHandler


def _text(content: str) -> list[dict]:
    return [{"type": "text", "text": content}]


def _list_issues(arguments: dict) -> tuple[list[dict], bool]:
    state = str(arguments.get("state") or "open")
    per_page = int(arguments.get("per_page") or 3)
    lines = [
        f"#{12 + index} [issue] {state} 状态的示例 issue {index + 1}"
        for index in range(max(per_page, 0))
    ]
    return _text(f"Found {len(lines)} issues ({state}):\n" + "\n".join(lines)), False


def _search_web(arguments: dict) -> tuple[list[dict], bool]:
    query = str(arguments.get("q") or "")
    results = "\n".join(
        f"{index + 1}. 关于「{query}」的示例结果 https://example.com/{index + 1}"
        for index in range(3)
    )
    return _text(f"搜索「{query}」得到 3 条结果：\n{results}"), False


def _read_broken_report(arguments: dict) -> tuple[list[dict], bool]:
    path = str(arguments.get("path") or "/reports/missing.csv")
    return _text(f"无法读取文件：{path}（模拟失败的 Tool）"), True


def _query_slow_data(arguments: dict) -> tuple[list[dict], bool]:
    seconds = float(arguments.get("seconds") or DEFAULT_SLOW_SECONDS)
    time.sleep(max(seconds, 0.0))
    return _text(f"慢查询在 {seconds:.1f}s 后返回（用于演示 Tool Call 超时）"), False


TOOLS: tuple[DemoTool, ...] = (
    DemoTool(
        name="list_issues",
        description="列出仓库中的 issue（模拟 GitHub），演示成功路径",
        input_schema={
            "type": "object",
            "properties": {
                "state": {"type": "string", "enum": ["open", "closed"]},
                "per_page": {"type": "integer"},
            },
        },
        handler=_list_issues,
    ),
    DemoTool(
        name="search_web",
        description="搜索互联网并返回模拟结果，演示成功路径",
        input_schema={
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        },
        handler=_search_web,
    ),
    DemoTool(
        name="read_broken_report",
        description="读取一份永远失败的报表，演示错误路径（isError=true）",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
        },
        handler=_read_broken_report,
    ),
    DemoTool(
        name="query_slow_data",
        description="一个很慢的查询，演示超时路径（默认 sleep 35s）",
        input_schema={
            "type": "object",
            "properties": {"seconds": {"type": "number"}},
        },
        handler=_query_slow_data,
    ),
)

_TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}


def list_tool_schemas() -> list[dict]:
    """`tools/list` 的返回体（`inputSchema` 为 JSON Schema）。"""
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.input_schema,
        }
        for tool in TOOLS
    ]


def dispatch(message: dict) -> dict | None:
    """处理一条 JSON-RPC 消息；通知返回 None（不应答）。"""
    method = message.get("method")
    request_id = message.get("id")

    if method == "notifications/initialized" or (
        request_id is None and isinstance(method, str) and method.startswith("notifications/")
    ):
        return None
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        )
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": list_tool_schemas()})
    if method == "tools/call":
        return _call_tool(request_id, message.get("params") or {})
    return _error(request_id, -32601, f"未实现的方法：{method}")


def _call_tool(request_id: Any, params: dict) -> dict:
    name = str(params.get("name") or "")
    arguments = params.get("arguments") or {}
    tool = _TOOLS_BY_NAME.get(name)
    if tool is None:
        return _error(request_id, -32602, f"未知 Tool：{name}")
    try:
        content, is_error = tool.handler(dict(arguments))
    except Exception as exc:  # 兜底：Tool 崩溃也应作为 isError 结果返回
        logger.exception("Demo Tool %s 执行异常", name)
        content, is_error = _text(f"Tool 内部错误：{type(exc).__name__}: {exc}"), True
    return _result(request_id, {"content": content, "isError": is_error})


def _result(request_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class McpRequestHandler(BaseHTTPRequestHandler):
    """单个 `POST /mcp` 端点的 Streamable HTTP 处理器。"""

    protocol_version = "HTTP/1.1"
    server_version = "AgentHubDemoMCPServer/0.1"

    def do_POST(self) -> None:  # noqa: N802（BaseHTTPRequestHandler 约定）
        if urlparse(self.path).path != MCP_PATH:
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            message = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send_json(200, _error(None, -32700, "请求体不是合法 JSON"))
            return

        response = dispatch(message)
        if response is None:  # 通知不应答
            self._send_empty(202)
            return

        extra_headers = None
        if message.get("method") == "initialize":
            extra_headers = {"Mcp-Session-Id": self.server.session_id}  # type: ignore[attr-defined]
        self._send_json(200, response, extra_headers)

    def do_GET(self) -> None:  # noqa: N802
        self._send_empty(405, extra_headers={"Allow": "POST"})

    def do_DELETE(self) -> None:  # noqa: N802（会话终止；Demo 无状态，直接 204）
        self._send_empty(204)

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug("%s - %s", self.address_string(), fmt % args)

    def _send_json(
        self, status: int, payload: dict, extra_headers: dict[str, str] | None = None
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._write(status, body, {"Content-Type": "application/json; charset=utf-8"}, extra_headers)

    def _send_empty(self, status: int, extra_headers: dict[str, str] | None = None) -> None:
        self._write(status, b"", {}, extra_headers)

    def _write(
        self,
        status: int,
        body: bytes,
        base_headers: dict[str, str],
        extra_headers: dict[str, str] | None,
    ) -> None:
        self.send_response(status)
        for key, value in {**base_headers, **(extra_headers or {})}.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # 客户端提前断开（如演示超时）：服务端无副作用，忽略
                logger.debug("客户端已断开，丢弃响应")


def build_server(host: str = "127.0.0.1", port: int = 8100) -> ThreadingHTTPServer:
    """创建（但不启动）Demo MCP Server，供 `main()` 与测试复用。"""
    server = ThreadingHTTPServer((host, port), McpRequestHandler)
    server.session_id = uuid.uuid4().hex  # type: ignore[attr-defined]
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentHub Demo MCP Server（streamable_http）")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")
    server = build_server(args.host, args.port)
    logger.info("Demo MCP Server 监听 http://%s:%d%s", args.host, args.port, MCP_PATH)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("收到中断，正在关闭")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
