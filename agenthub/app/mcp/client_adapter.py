"""MCP Client 适配层。设计文档 §8.2 / 契约 §6.1、§2.6。归属：B（MCP Hub）。

业务层（`router` / `discovery`）只依赖 `McpClientAdapter`；Transport 细节（JSON-RPC 报文、
SSE 解析、session 管理）全部收敛在本模块。V1 仅支持 `streamable_http`，用 httpx 实现，
不引入官方 MCP SDK（本项目依赖策略：复用既有依赖）。

超时约定：httpx 不设 read 超时（`read=None`），RPC 的整体超时由调用方用
`asyncio.wait_for` 控制——Discovery 用 10s（契约 §4.2.5），Tool Call 用
`ToolContext.timeout_ms`（契约 §6.1，默认 30s）。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, Field

from app.core.enums import TransportType

logger = logging.getLogger(__name__)

# 契约 §1.5 错误码（用于 ToolResult / 接口层映射）
MCP_SERVER_UNREACHABLE = "MCP_SERVER_UNREACHABLE"
MCP_DISCOVERY_FAILED = "MCP_DISCOVERY_FAILED"
TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
TOOL_TIMEOUT = "TOOL_TIMEOUT"
INVALID_ARGUMENT = "INVALID_ARGUMENT"

# MCP 协议版本（Streamable HTTP）
MCP_PROTOCOL_VERSION = "2025-06-18"
# 连通性测试超时（契约 §4.2.5）
DISCOVERY_TIMEOUT_S = 10.0
_CLIENT_INFO = {"name": "agenthub", "version": "0.1.0"}


class McpClientError(RuntimeError):
    """MCP 通信失败。`error_code` 取契约 §1.5 的错误码。"""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class McpServerConfig(BaseModel):
    """建立 MCP 连接所需的最小信息（D 由 `mcp_server` 行映射得到）。"""

    id: int
    name: str
    endpoint: str
    transport: TransportType = TransportType.STREAMABLE_HTTP
    headers: dict[str, str] | None = None


class McpToolInfo(BaseModel):
    """`tools/list` 返回的一条原始 Tool 元数据（未经标准化）。"""

    name: str
    description: str = ""
    input_schema: dict = Field(default_factory=dict)
    read_only_hint: bool | None = None


class McpCallResult(BaseModel):
    """`tools/call` 的原始结果（`content` 未裁剪，契约 §7 的截断在 Trace 层做）。"""

    content: list[dict] = Field(default_factory=list)
    is_error: bool = False
    structured_content: dict | None = None


@runtime_checkable
class McpClientAdapter(Protocol):
    """单个 MCP Server 的连接抽象（设计文档 §8.2）。"""

    async def initialize(self) -> dict:
        """完成 MCP `initialize` 握手并返回 `serverInfo`。"""

    async def list_tools(self) -> list[McpToolInfo]:
        """调用 `tools/list`（自动处理分页），返回原始 Tool 列表。"""

    async def call_tool(self, remote_name: str, arguments: dict) -> McpCallResult:
        """调用 `tools/call`。协议层失败抛 `McpClientError`。"""


@runtime_checkable
class McpClientFactory(Protocol):
    """按 Server 创建 / 复用 MCP Client（设计文档 §8.3）。"""

    def for_server(self, server: McpServerConfig) -> McpClientAdapter: ...


@runtime_checkable
class McpServerProvider(Protocol):
    """`server_id -> McpServerConfig` 的查询边界。"""

    async def get(self, server_id: int) -> McpServerConfig | None: ...


def parse_sse_data(text: str) -> list[dict]:
    """从 `text/event-stream` 响应体中解析出所有 `data:` JSON 对象。

    忽略注释帧（`: keep-alive`）与非 JSON 数据；一个 `data:` 行是单行 JSON（契约 §5.1）。
    """
    messages: list[dict] = []
    data_lines: list[str] = []

    def flush() -> None:
        if not data_lines:
            return
        try:
            messages.append(json.loads("\n".join(data_lines)))
        except json.JSONDecodeError:
            logger.warning("忽略无法解析的 SSE data 帧：%s", "\n".join(data_lines)[:200])
        data_lines.clear()

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            flush()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].removeprefix(" "))
    flush()
    return messages


def select_rpc_message(messages: list[dict], request_id: int) -> dict | None:
    """从一批 JSON-RPC 消息中挑出本次请求的响应。

    Streamable HTTP 的响应可能是 SSE 流（含通知等其它消息），优先按 `id` 精确匹配；
    若无（服务端未回 `id` 时）则退回最后一条带 `result` / `error` 的消息。
    """
    for message in messages:
        if message.get("id") == request_id and ("result" in message or "error" in message):
            return message
    for message in reversed(messages):
        if "result" in message or "error" in message:
            return message
    return None


class StreamableHttpMcpClient:
    """基于 httpx 的 Streamable HTTP MCP 客户端（JSON-RPC 2.0）。

    首次请求前自动完成 `initialize` + `notifications/initialized`，并维护
    `Mcp-Session-Id`。`http_client` 可注入（测试用 `httpx.MockTransport`）。
    """

    def __init__(
        self,
        server: McpServerConfig,
        *,
        timeout_s: float = DISCOVERY_TIMEOUT_S,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if server.transport is not TransportType.STREAMABLE_HTTP:
            raise McpClientError(
                INVALID_ARGUMENT,
                f"V1 仅支持 streamable_http，收到：{server.transport.value}",
            )
        self._server = server
        self._timeout_s = timeout_s
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=timeout_s, read=None, write=timeout_s, pool=timeout_s)
        )
        self._session_id: str | None = None
        self._next_request_id = 0
        self._initialized = False
        self._server_info: dict = {}

    async def __aenter__(self) -> StreamableHttpMcpClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def initialize(self) -> dict:
        """幂等：已握手则直接返回 `serverInfo`。"""
        if self._initialized:
            return self._server_info
        result = await self._rpc(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": _CLIENT_INFO,
            },
        )
        self._server_info = dict(result)
        self._initialized = True
        await self._notify("notifications/initialized")
        return self._server_info

    async def list_tools(self) -> list[McpToolInfo]:
        await self._ensure_initialized()
        tools: list[McpToolInfo] = []
        cursor: str | None = None
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = await self._rpc("tools/list", params)
            tools.extend(_to_tool_info(raw) for raw in result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    async def call_tool(self, remote_name: str, arguments: dict) -> McpCallResult:
        await self._ensure_initialized()
        result = await self._rpc("tools/call", {"name": remote_name, "arguments": arguments})
        return McpCallResult(
            content=list(result.get("content") or []),
            is_error=bool(result.get("isError")),
            structured_content=result.get("structuredContent"),
        )

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()

    async def _rpc(self, method: str, params: dict) -> dict:
        self._next_request_id += 1
        request_id = self._next_request_id
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        response = await self._post(payload)
        if session_id := response.headers.get("mcp-session-id"):
            self._session_id = session_id
        if response.status_code >= 400:
            raise McpClientError(
                MCP_SERVER_UNREACHABLE,
                f"MCP Server 返回 HTTP {response.status_code}：{response.text[:200]}",
            )
        message = select_rpc_message(self._decode(response), request_id)
        if message is None:
            raise McpClientError(MCP_DISCOVERY_FAILED, f"{method} 未返回可解析的 JSON-RPC 响应")
        if error := message.get("error"):
            raise McpClientError(
                TOOL_EXECUTION_FAILED,
                f"{method} 失败：{error.get('code')} {error.get('message')}",
            )
        return dict(message.get("result") or {})

    async def _notify(self, method: str) -> None:
        """发送 JSON-RPC 通知（无响应）。失败只记日志，不影响主流程。"""
        payload = {"jsonrpc": "2.0", "method": method, "params": {}}
        try:
            response = await self._post(payload)
        except McpClientError as exc:
            logger.warning("MCP 通知 %s 发送失败：%s", method, exc.message)
            return
        if session_id := response.headers.get("mcp-session-id"):
            self._session_id = session_id

    async def _post(self, payload: dict) -> httpx.Response:
        try:
            return await self._client.post(
                self._server.endpoint,
                json=payload,
                headers=self._headers(),
            )
        except httpx.TimeoutException as exc:
            raise McpClientError(TOOL_TIMEOUT, f"MCP 请求超时：{exc}") from exc
        except httpx.HTTPError as exc:
            raise McpClientError(MCP_SERVER_UNREACHABLE, f"MCP 连接失败：{exc}") from exc

    def _headers(self) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        }
        if self._server.headers:
            headers.update(self._server.headers)
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        return headers

    @staticmethod
    def _decode(response: httpx.Response) -> list[dict]:
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return parse_sse_data(response.text)
        try:
            return [response.json()]
        except (json.JSONDecodeError, ValueError):
            return []


class HttpMcpClientFactory:
    """`McpClientFactory` 的默认实现：按 `server_id` 复用客户端，避免每次调用新建连接。

    Server 配置变更（`PUT /api/mcp/servers/{id}`）后应调用 `invalidate()` 丢弃旧连接。
    """

    def __init__(self, *, timeout_s: float = DISCOVERY_TIMEOUT_S) -> None:
        self._timeout_s = timeout_s
        self._clients: dict[int, StreamableHttpMcpClient] = {}

    def for_server(self, server: McpServerConfig) -> McpClientAdapter:
        client = self._clients.get(server.id)
        if client is None:
            client = StreamableHttpMcpClient(server, timeout_s=self._timeout_s)
            self._clients[server.id] = client
        return client

    async def invalidate(self, server_id: int) -> None:
        client = self._clients.pop(server_id, None)
        if client is not None:
            await client.aclose()

    async def aclose(self) -> None:
        clients, self._clients = self._clients, {}
        for client in clients.values():
            await client.aclose()


def _to_tool_info(raw: dict) -> McpToolInfo:
    annotations = raw.get("annotations")
    read_only_hint = annotations.get("readOnlyHint") if isinstance(annotations, dict) else None
    return McpToolInfo(
        name=str(raw.get("name") or ""),
        description=str(raw.get("description") or ""),
        input_schema=dict(raw.get("inputSchema") or {}),
        read_only_hint=bool(read_only_hint) if read_only_hint is not None else None,
    )
