"""Tool Router —— `McpToolGateway` 的实现。设计文档 §8.3 / 契约 §6.1。归属：B（MCP Hub）。

执行链路（设计文档 §8.3）::

    Registry 查询 -> 绑定校验 -> Permission Guard -> input_schema 校验 -> tools/call

约定：**不抛业务异常**，任何失败都以 `ToolResult(ok=False, error_code=...)` 返回（契约 §6.1），
从而 A（Runtime）可以把失败转成一次 TOOL_CALL_FINISHED 事件而不是崩溃。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from app.mcp.client_adapter import (
    MCP_SERVER_UNREACHABLE,
    TOOL_EXECUTION_FAILED,
    TOOL_TIMEOUT,
    McpClientError,
    McpClientFactory,
    McpServerProvider,
)
from app.mcp.gateway import McpToolGateway
from app.mcp.schemas import ToolCall, ToolContext, ToolDefinition, ToolResult
from app.tools.permission import PermissionGuard, ToolPermissionDenied
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# 契约 §6.1：ToolResult.content 为「已裁剪」的 MCP content；§7 体积截断 64 KB
PAYLOAD_LIMIT_BYTES = 64 * 1024

_TYPE_CHECKERS: dict[str, Any] = {
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "array": lambda value: isinstance(value, list),
    "object": lambda value: isinstance(value, dict),
    "null": lambda value: value is None,
}


def validate_arguments(schema: dict, arguments: dict) -> str | None:
    """按 `input_schema`（JSON Schema 子集）校验入参，返回错误描述；通过则返回 None。

    只覆盖 MCP Tool 常见的 `type` / `required` / `properties` / `items` / `enum` /
    `additionalProperties`；未识别的关键字一律宽松放过，避免误报 `TOOL_SCHEMA_INVALID`。
    """
    if not isinstance(schema, dict) or not schema:
        return None
    if schema.get("type") not in (None, "object"):
        # 非 object 的 schema 在 Discovery 阶段已按契约 §10 D9 置为 {} + disabled
        return None
    return _validate(arguments, schema, "$")


def flatten_content(content: list[dict]) -> str:
    """把 MCP content 数组拼平为文本，用于回填 Observation（契约 §6.1 ToolResult.text）。"""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
        else:
            parts.append(json.dumps(item, ensure_ascii=False))
    return "\n".join(parts)


class ToolRouter(McpToolGateway):
    """`list_tools` / `execute_tool` 的实现。"""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        servers: McpServerProvider,
        client_factory: McpClientFactory,
        permission: PermissionGuard | None = None,
    ) -> None:
        self._registry = registry
        self._servers = servers
        self._client_factory = client_factory
        self._permission = permission or PermissionGuard()

    async def list_tools(self, *, agent_id: int) -> list[ToolDefinition]:
        return await self._registry.list_bound_tools(agent_id=agent_id)

    async def execute_tool(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        started = time.perf_counter()

        tool = await self._registry.get_by_qualified_name(call.qualified_name)
        if tool is None:
            return _failure(call, "TOOL_NOT_FOUND", f"Tool 不存在：{call.qualified_name}", started)

        if not await self._registry.is_bound(agent_id=ctx.agent_id, tool_id=tool.id):
            return _failure(
                call, "TOOL_NOT_BOUND", f"Tool 未被该 Agent 绑定：{call.qualified_name}", started
            )

        try:
            self._permission.check(agent_id=ctx.agent_id, tool=tool)
        except ToolPermissionDenied as exc:
            return _failure(call, exc.error_code, exc.message, started)

        if error := validate_arguments(tool.input_schema, call.arguments):
            return _failure(call, "TOOL_SCHEMA_INVALID", f"入参不符合 input_schema：{error}", started)

        server = await self._servers.get(tool.server_id)
        if server is None:
            return _failure(
                call, MCP_SERVER_UNREACHABLE, f"MCP Server 不存在：{tool.server_id}", started
            )

        client = self._client_factory.for_server(server)
        try:
            result = await asyncio.wait_for(
                client.call_tool(tool.remote_name, call.arguments),
                timeout=ctx.timeout_ms / 1000,
            )
        except TimeoutError:
            return _failure(
                call,
                TOOL_TIMEOUT,
                f"MCP tool call timed out after {ctx.timeout_ms}ms",
                started,
            )
        except McpClientError as exc:
            return _failure(call, exc.error_code, exc.message, started)
        except Exception as exc:  # 兜底：违反契约的实现也不能让 Runtime 崩溃
            logger.exception("Tool %s 执行时发生未归类异常", call.qualified_name)
            return _failure(
                call, TOOL_EXECUTION_FAILED, f"{type(exc).__name__}: {exc}"[:512], started
            )

        text = flatten_content(result.content)
        content = _trim_content(result.content)
        if result.is_error:
            return _failure(
                call,
                TOOL_EXECUTION_FAILED,
                text or "MCP tools/call 返回 isError=true",
                started,
                content=content,
                text=text,
            )
        return ToolResult(
            call_id=call.call_id,
            qualified_name=call.qualified_name,
            ok=True,
            content=content,
            text=text,
            duration_ms=_elapsed_ms(started),
        )


def _validate(value: Any, schema: dict, path: str) -> str | None:
    if not isinstance(schema, dict):
        return None
    if "type" in schema and not _matches_type(value, schema["type"]):
        return f"{path} 类型不符合 schema（期望 {schema['type']}）"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path} 取值不在 enum 内"
    if isinstance(value, dict):
        for key in schema.get("required") or []:
            if key not in value:
                return f"{path}.{key} 为必填项"
        properties = schema.get("properties") or {}
        for key, sub_schema in properties.items():
            if key in value:
                if error := _validate(value[key], sub_schema, f"{path}.{key}"):
                    return error
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    return f"{path}.{key} 为未定义字段"
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            if error := _validate(item, schema["items"], f"{path}[{index}]"):
                return error
    return None


def _matches_type(value: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return any(_matches_type(value, candidate) for candidate in expected)
    checker = _TYPE_CHECKERS.get(expected)
    return True if checker is None else bool(checker(value))


def _trim_content(content: list[dict]) -> list[dict]:
    """契约 §7 体积截断：序列化后超过 64 KB 则丢弃 content，只保留 text。"""
    if not content:
        return []
    if len(json.dumps(content, ensure_ascii=False).encode("utf-8")) > PAYLOAD_LIMIT_BYTES:
        return []
    return content


def _failure(
    call: ToolCall,
    error_code: str,
    error_message: str,
    started: float,
    *,
    content: list[dict] | None = None,
    text: str = "",
) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        qualified_name=call.qualified_name,
        ok=False,
        content=content or [],
        text=text,
        duration_ms=_elapsed_ms(started),
        error_code=error_code,
        error_message=error_message,
    )


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
