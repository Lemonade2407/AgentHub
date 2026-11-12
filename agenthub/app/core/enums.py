"""契约 §2 冻结的枚举全集。

归属：公共（A/B/C/D 共用）。变更需走《接口契约文档》§0.2 流程。

约定：数据库中一律以 varchar 存储，取值与下列字符串完全一致（UPPER_SNAKE）。
"""

from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    """契约 §2.1 —— 一次 Run 的生命周期状态。"""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StopReason(StrEnum):
    """契约 §2.2 —— Run 为何结束。"""

    FINISHED = "FINISHED"
    MAX_STEPS = "MAX_STEPS"
    MODEL_ERROR = "MODEL_ERROR"
    TOOL_ERROR = "TOOL_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    CANCELLED = "CANCELLED"


class StepStatus(StrEnum):
    """契约 §2.3 —— 单个 Trace 事件的执行结果。"""

    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class RiskLevel(StrEnum):
    """契约 §2.4 —— Tool 风险级别。"""

    READ_ONLY = "READ_ONLY"
    LOW_RISK = "LOW_RISK"
    WRITE = "WRITE"
    HIGH_RISK = "HIGH_RISK"


class TraceEventType(StrEnum):
    """契约 §2.7 —— Trace 事件类型。

    落库（`agent_step.event_type`）用 UPPER_SNAKE；
    SSE 的 `event:` 字段取其小写形式（`TraceEventType.value.lower()`）。
    """

    RUN_STARTED = "RUN_STARTED"
    LLM_STARTED = "LLM_STARTED"
    LLM_FINISHED = "LLM_FINISHED"
    TOOL_CANDIDATES = "TOOL_CANDIDATES"
    # V2：本次 Run 生效的 Skill 与缺失的 Skill 工具（step_no = 0）
    SKILL_INJECTED = "SKILL_INJECTED"
    SKILL_TOOL_MISSING = "SKILL_TOOL_MISSING"
    TOOL_CALL_STARTED = "TOOL_CALL_STARTED"
    TOOL_CALL_FINISHED = "TOOL_CALL_FINISHED"
    STATE_UPDATED = "STATE_UPDATED"
    RUN_FINISHED = "RUN_FINISHED"
    RUN_FAILED = "RUN_FAILED"


class McpServerStatus(StrEnum):
    """契约 §2.5 —— MCP Server 连通性状态。

    注意与 `mcp_server.status` 的区分：`UNKNOWN` 为注册后未测试的初始值。
    """

    UNKNOWN = "UNKNOWN"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"


class TransportType(StrEnum):
    """契约 §2.6 —— MCP Transport。

    V1 仅支持 `streamable_http`；`stdio` 为 P2（本模块对未知 / 不支持的值一律拒绝）。
    """

    STREAMABLE_HTTP = "streamable_http"
    STDIO = "stdio"


# ---------------------------------------------------------------------------
# V2 新增枚举（修改意见文档 §3.2 / §4.3 / §5.3）
#
# 注意：V2 新表的枚举值统一采用**小写 snake**（与修改意见草案一致），
# 不再沿用 V1 的 UPPER_SNAKE；V1 既有表的枚举值保持不变。
# ---------------------------------------------------------------------------


class UserStatus(StrEnum):
    """`app_user.status` —— 账号状态。"""

    ACTIVE = "active"
    DISABLED = "disabled"


class ModelProvider(StrEnum):
    """`model_api.provider` —— 模型提供方；`custom` 表示自建网关 / 代理。"""

    DEEPSEEK = "deepseek"
    OPENAI = "openai"
    QWEN = "qwen"
    CUSTOM = "custom"


class SkillVisibility(StrEnum):
    """`skill.visibility` —— 公开 / 私有。"""

    PRIVATE = "private"
    PUBLIC = "public"


class SkillStatus(StrEnum):
    """`skill.status` —— Skill 生命周期状态。"""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class SkillCategory(StrEnum):
    """`skill.category` 与 `agent_publication.category`。"""

    GENERAL = "general"
    WRITING = "writing"
    CODING = "coding"
    DATA = "data"
    RESEARCH = "research"
    OPS = "ops"


class PublicationStatus(StrEnum):
    """`agent_publication.status` —— 发布快照生命周期状态。"""

    DRAFT = "draft"
    PUBLISHED = "published"
    OFFLINE = "offline"
