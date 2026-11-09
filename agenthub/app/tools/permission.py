"""Permission Guard。设计文档 §8.3 / 契约 §2.4、§1.5。归属：B（MCP Hub）。

V1 策略（契约 §10 D2，不提供任何人工放行开关）：

| 风险级别 | 策略 |
|---|---|
| `READ_ONLY` | 允许 |
| `LOW_RISK` | 需显式启用（`ToolDefinition.enabled` 即为该开关） |
| `WRITE` | 一律拒绝 |
| `HIGH_RISK` | 一律拒绝（Discovery 阶段已丢弃，此处兜底） |
"""

from __future__ import annotations

from app.core.enums import RiskLevel
from app.mcp.schemas import ToolDefinition

# V1 一律拒绝的风险级别（契约 §2.4）
DENIED_RISK_LEVELS: frozenset[RiskLevel] = frozenset({RiskLevel.WRITE, RiskLevel.HIGH_RISK})


class ToolPermissionDenied(RuntimeError):
    """权限校验失败。`error_code` 取契约 §1.5 的错误码。"""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class PermissionGuard:
    """Tool 执行前的权限判定。"""

    def check(self, *, agent_id: int | None, tool: ToolDefinition) -> None:
        """不通过时抛 `ToolPermissionDenied`；通过返回 None。

        `agent_id` 目前不参与判定，保留它是为了将来按 Agent 维度做白名单；
        这里显式接收以便调用方在审计日志中记录。
        """
        if not tool.enabled:
            raise ToolPermissionDenied(
                "TOOL_RISK_DENIED",
                f"Tool 未启用：{tool.qualified_name}",
            )
        if tool.risk_level in DENIED_RISK_LEVELS:
            raise ToolPermissionDenied(
                "TOOL_RISK_DENIED",
                f"风险级别 {tool.risk_level.value} 在 V1 一律拒绝：{tool.qualified_name}",
            )
