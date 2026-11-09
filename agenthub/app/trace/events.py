"""契约 §3.5 / §6.3 冻结 DTO 与接口。归属：D（Trace Service）。

A（Runtime）只负责构造 `TraceEvent` 并 `emit`，不关心持久化与 SSE。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.core.enums import StepStatus, TraceEventType


def utcnow() -> datetime:
    """统一 UTC 时间源（数据库设计文档 §1：全部以 UTC 存储）。"""
    return datetime.now(UTC)


class TraceEvent(BaseModel):
    """统一 Trace 事件。既是 `agent_step` 行的内存形态，也是 SSE 的载荷。"""

    id: int | None = None
    run_id: str
    step_no: int
    event_type: TraceEventType
    status: StepStatus
    node: str | None = None
    tool: str | None = None
    duration_ms: int | None = None
    data: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utcnow)


@runtime_checkable
class TraceSink(Protocol):
    """Trace 写入边界。"""

    async def emit(self, event: TraceEvent) -> None:
        """投递一个事件。

        约定（契约 §6.3）：
        - **必须非阻塞且不抛异常**：DB 写失败只记日志，不得阻断 Runtime；
        - 负责分配 `id`（= `agent_step.id`，同时作为 SSE 的 `id`）、持久化、投递队列；
        - `step_no` 由调用方（Runtime）提供，语义见契约 §3.4。
        """
