"""Run 与 Trace 相关 DTO。契约 §3.4 / §3.6。归属：D（Platform Backend）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.enums import RunStatus, StepStatus, StopReason, TraceEventType


class RunCreateRequest(BaseModel):
    input: str = Field(min_length=1, max_length=10000)
    max_steps: int | None = Field(default=None, ge=1, le=20)


class RunRead(BaseModel):
    id: str
    agent_id: int
    thread_id: str
    status: RunStatus
    stop_reason: StopReason | None
    input: str
    output: str | None
    error_code: str | None
    error_message: str | None
    max_steps: int
    llm_calls: int
    tool_calls: int
    step_count: int
    duration_ms: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class StepRead(BaseModel):
    id: int
    run_id: str
    step_no: int
    event_type: TraceEventType
    status: StepStatus
    node: str | None
    tool: str | None
    duration_ms: int | None
    payload: dict[str, Any]
    created_at: datetime
