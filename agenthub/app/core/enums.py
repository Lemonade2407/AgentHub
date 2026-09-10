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
    TOOL_CALL_STARTED = "TOOL_CALL_STARTED"
    TOOL_CALL_FINISHED = "TOOL_CALL_FINISHED"
    STATE_UPDATED = "STATE_UPDATED"
    RUN_FINISHED = "RUN_FINISHED"
    RUN_FAILED = "RUN_FAILED"
