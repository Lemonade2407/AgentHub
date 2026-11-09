"""Tool Discovery 与风险推断。设计文档 §8.1 / 契约 §3.2、§3.3、§4.2.6（D9）。归属：B（MCP Hub）。

职责：
1. 连通性测试（契约 §4.2.5）：MCP `initialize` + 延迟统计；
2. Tool Discovery（契约 §4.2.6）：`tools/list` → 标准化 → 按 `(server_id, remote_name)` upsert；
3. 风险级别自动推断（契约 §3.3）与 `server_slug` 派生（契约 §3.2）。

Discovery 边界规则（契约 §10 D9）：
- `remote_name` 超过 128 字符 → 跳过并记 warning；
- `input_schema` 非 `type: object`（非法）→ 以 `{}` 入库并 `enabled=false`；
- 识别为 `HIGH_RISK` 的 Tool → 丢弃，不入库；
- 本次未返回的 Tool → 置 `enabled=false`（不物理删除）。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.core.enums import McpServerStatus, RiskLevel
from app.mcp.client_adapter import (
    DISCOVERY_TIMEOUT_S,
    MCP_DISCOVERY_FAILED,
    MCP_SERVER_UNREACHABLE,
    TOOL_TIMEOUT,
    McpClientError,
    McpClientFactory,
    McpServerConfig,
)
from app.mcp.schemas import McpDiscoverResult, McpServerTestResult

logger = logging.getLogger(__name__)

# 契约 §10 D9：remote_name 上限（数据库 varchar(128)）
REMOTE_NAME_MAX_LENGTH = 128

_READ_PREFIX = re.compile(r"^(get|list|search|query|read|fetch|find|describe)_")
_WRITE_PREFIX = re.compile(r"^(create|update|write|put|post|delete|remove|drop)_")
_HIGH_RISK = re.compile(r"(^|_)(shell|exec|command|payment|transfer)($|_)")
_SLUG_INVALID = re.compile(r"[^a-z0-9]+")


def server_slug(name: str) -> str:
    """契约 §3.2：`name` 小写化，非 `[a-z0-9]` 替换为 `_`，压缩连续 `_`，去除首尾 `_`。

    示例：`GitHub MCP` → `github_mcp`。
    """
    return _SLUG_INVALID.sub("_", name.lower()).strip("_")


def infer_risk_level(remote_name: str, *, read_only_hint: bool | None = None) -> RiskLevel:
    """契约 §3.3：按固定优先级自动推断风险级别。"""
    if read_only_hint is True:
        return RiskLevel.READ_ONLY
    if _READ_PREFIX.search(remote_name):
        return RiskLevel.READ_ONLY
    if _WRITE_PREFIX.search(remote_name):
        return RiskLevel.WRITE
    if _HIGH_RISK.search(remote_name):
        return RiskLevel.HIGH_RISK
    return RiskLevel.LOW_RISK


class ToolUpsertOutcome(StrEnum):
    """`(server_id, remote_name)` upsert 的结果，用于统计 `added` / `updated`。"""

    ADDED = "ADDED"
    UPDATED = "UPDATED"


class NormalizedTool(BaseModel):
    """标准化后的 Tool 元数据（写入 `mcp_tool` 的内容，不含 `id` / `updated_at`）。"""

    server_id: int
    remote_name: str
    qualified_name: str
    description: str = ""
    input_schema: dict = Field(default_factory=dict)
    risk_level: RiskLevel
    enabled: bool = True


@runtime_checkable
class ToolRegistryStore(Protocol):
    """Discovery 写入 Tool Registry 的边界（D 用 `mcp_tool` 实现）。"""

    async def upsert_tool(self, tool: NormalizedTool) -> ToolUpsertOutcome:
        """以 `(server_id, remote_name)` 为冲突键 upsert，返回本次是新增还是更新。"""

    async def disable_tools_not_returned(self, *, server_id: int, remote_names: set[str]) -> int:
        """把该 Server 下不在 `remote_names` 中的 Tool 置 `enabled=false`，返回受影响行数。"""

    async def count_tools(self, *, server_id: int) -> int:
        """该 Server 当前的 Tool 总数（含已禁用）。"""


@runtime_checkable
class McpServerStore(Protocol):
    """Discovery / 连通性测试回写 `mcp_server` 状态的边界。"""

    async def update_status(
        self, *, server_id: int, status: McpServerStatus, last_error: str | None
    ) -> None:
        """更新 `status` 与 `last_error`（`last_error=None` 表示清空）。"""

    async def mark_discovered(self, *, server_id: int, discovered_at: datetime) -> None:
        """更新 `last_discovered_at`。"""


class McpDiscoveryError(RuntimeError):
    """Discovery 失败（不可达 / 解析失败），由 D 映射为 `502 MCP_DISCOVERY_FAILED`。"""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class DiscoveryService:
    """连通性测试 + Tool Discovery。"""

    def __init__(
        self,
        *,
        registry_store: ToolRegistryStore,
        server_store: McpServerStore,
        client_factory: McpClientFactory,
        timeout_s: float = DISCOVERY_TIMEOUT_S,
    ) -> None:
        self._registry_store = registry_store
        self._server_store = server_store
        self._client_factory = client_factory
        self._timeout_s = timeout_s

    async def test_connection(self, server: McpServerConfig) -> McpServerTestResult:
        """契约 §4.2.5：MCP `initialize`，业务失败也返回结果（靠 `ok` 判断）。"""
        started = time.perf_counter()
        client = self._client_factory.for_server(server)
        try:
            server_info = await asyncio.wait_for(client.initialize(), timeout=self._timeout_s)
        except McpClientError as exc:
            return await self._record_failure(server, exc.error_code, exc.message, started)
        except TimeoutError:
            code = TOOL_TIMEOUT
            return await self._record_failure(
                server, code, f"连通性测试超时（{self._timeout_s}s）", started
            )
        except Exception as exc:  # 兜底：协议实现异常不应冒泡成 500
            logger.exception("MCP Server %s 连通性测试异常", server.name)
            return await self._record_failure(
                server, MCP_SERVER_UNREACHABLE, f"{type(exc).__name__}: {exc}"[:512], started
            )

        await self._server_store.update_status(
            server_id=server.id, status=McpServerStatus.CONNECTED, last_error=None
        )
        return McpServerTestResult(
            ok=True,
            status=McpServerStatus.CONNECTED,
            latency_ms=_elapsed_ms(started),
            server_info=server_info,
        )

    async def discover(self, server: McpServerConfig) -> McpDiscoverResult:
        """契约 §4.2.6：拉取 `tools/list` 并标准化写入 Registry。

        失败时更新 `status=ERROR` + `last_error`，并抛 `McpDiscoveryError`。
        """
        started = time.perf_counter()
        client = self._client_factory.for_server(server)
        try:
            infos = await asyncio.wait_for(client.list_tools(), timeout=self._timeout_s)
        except McpClientError as exc:
            await self._server_store.update_status(
                server_id=server.id, status=McpServerStatus.ERROR, last_error=exc.message
            )
            raise McpDiscoveryError(MCP_DISCOVERY_FAILED, exc.message) from exc
        except TimeoutError as exc:
            message = f"Discovery 超时（{self._timeout_s}s）"
            await self._server_store.update_status(
                server_id=server.id, status=McpServerStatus.ERROR, last_error=message
            )
            raise McpDiscoveryError(MCP_DISCOVERY_FAILED, message) from exc
        except Exception as exc:
            logger.exception("MCP Server %s Discovery 异常", server.name)
            message = f"{type(exc).__name__}: {exc}"[:512]
            await self._server_store.update_status(
                server_id=server.id, status=McpServerStatus.ERROR, last_error=message
            )
            raise McpDiscoveryError(MCP_DISCOVERY_FAILED, message) from exc

        slug = server_slug(server.name) or f"server{server.id}"
        added = updated = 0
        returned: set[str] = set()
        for info in infos:
            if not info.name:
                logger.warning("Discovery 跳过无名 Tool（server=%s）", server.name)
                continue
            if len(info.name) > REMOTE_NAME_MAX_LENGTH:
                logger.warning(
                    "Discovery 跳过超长 Tool 名（server=%s, len=%d）", server.name, len(info.name)
                )
                continue

            risk_level = infer_risk_level(info.name, read_only_hint=info.read_only_hint)
            if risk_level is RiskLevel.HIGH_RISK:
                logger.warning("Discovery 丢弃 HIGH_RISK Tool：%s", info.name)
                continue

            input_schema, enabled = _normalize_schema(info.input_schema)
            outcome = await self._registry_store.upsert_tool(
                NormalizedTool(
                    server_id=server.id,
                    remote_name=info.name,
                    qualified_name=f"{slug}.{info.name}",
                    description=info.description,
                    input_schema=input_schema,
                    risk_level=risk_level,
                    enabled=enabled,
                )
            )
            if outcome is ToolUpsertOutcome.ADDED:
                added += 1
            else:
                updated += 1
            returned.add(info.name)

        removed = await self._registry_store.disable_tools_not_returned(
            server_id=server.id, remote_names=returned
        )
        total = await self._registry_store.count_tools(server_id=server.id)
        await self._server_store.update_status(
            server_id=server.id, status=McpServerStatus.CONNECTED, last_error=None
        )
        await self._server_store.mark_discovered(
            server_id=server.id, discovered_at=datetime.now(UTC)
        )

        return McpDiscoverResult(
            server_id=server.id,
            status=McpServerStatus.CONNECTED,
            added=added,
            updated=updated,
            removed=removed,
            total=total,
            duration_ms=_elapsed_ms(started),
        )

    async def _record_failure(
        self, server: McpServerConfig, error_code: str, message: str, started: float
    ) -> McpServerTestResult:
        await self._server_store.update_status(
            server_id=server.id, status=McpServerStatus.ERROR, last_error=message
        )
        return McpServerTestResult(
            ok=False,
            status=McpServerStatus.ERROR,
            latency_ms=_elapsed_ms(started),
            error_code=error_code,
            error_message=message,
        )


def _normalize_schema(schema: object) -> tuple[dict, bool]:
    """契约 §10 D9：非法 schema（非 `type: object`）以 `{}` 入库并置 `enabled=false`。"""
    if isinstance(schema, dict) and schema.get("type") == "object":
        return schema, True
    return {}, False


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
