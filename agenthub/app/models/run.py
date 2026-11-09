"""`agent_run` / `agent_step` 模型（数据库设计文档 §3.5、§3.6）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import RunStatus, StepStatus, StopReason, TraceEventType
from app.models.base import Base, in_clause


class AgentRun(Base):
    """一次 Agent 运行记录。"""

    __tablename__ = "agent_run"
    __table_args__ = (
        CheckConstraint(in_clause("status", RunStatus), name="status"),
        CheckConstraint(
            f"stop_reason IS NULL OR {in_clause('stop_reason', StopReason)}",
            name="stop_reason",
        ),
        CheckConstraint("max_steps BETWEEN 1 AND 20", name="max_steps"),
        Index(
            "idx_agent_run_agent_id_created_at",
            "agent_id",
            text("created_at DESC"),
        ),
        Index(
            "idx_agent_run_status_created_at",
            "status",
            text("created_at DESC"),
        ),
        {"comment": "一次 Agent 运行记录"},
    )

    # r_ + 12 位小写十六进制（契约 §4.3）
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    agent_id: Mapped[int] = mapped_column(
        BigInteger,
        # Run 是审计资产：Agent 只做软删除，物理删除须被拦下
        ForeignKey("agent.id", ondelete="RESTRICT"),
    )
    thread_id: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        String(16), server_default=RunStatus.PENDING.value
    )
    stop_reason: Mapped[str | None] = mapped_column(String(16))
    input: Mapped[str] = mapped_column(Text)
    output: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(String(512))
    # 本次 Run 实际生效的 max_steps 快照，用于复现 MAX_STEPS 判定
    max_steps: Mapped[int] = mapped_column(
        SmallInteger,
        comment="本次 Run 实际生效的 max_steps 快照，用于复现",
    )
    llm_calls: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    tool_calls: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # = MAX(agent_step.step_no)，Run 结束时冗余写入
    step_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentStep(Base):
    """Trace / 执行步骤；`id` 同时作为 SSE 的事件 id。"""

    __tablename__ = "agent_step"
    __table_args__ = (
        CheckConstraint(in_clause("event_type", TraceEventType), name="event_type"),
        CheckConstraint(in_clause("status", StepStatus), name="status"),
        CheckConstraint(
            "node IS NULL OR node IN ('model_node', 'tools_node')", name="node"
        ),
        CheckConstraint("step_no >= 0", name="step_no"),
        Index("idx_agent_step_run_step_no", "run_id", "step_no", "id"),
        Index("idx_agent_step_run_id_id", "run_id", "id"),
        {"comment": "Trace / 执行步骤；id 同时作为 SSE 的事件 id"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("agent_run.id", ondelete="CASCADE"),
    )
    # 0 = Run 级事件；同一 step_no 可有多条事件，绝不做唯一约束（§9 D-DB3）
    step_no: Mapped[int] = mapped_column(
        Integer,
        comment="图执行步序号；0 为 Run 级事件；同一 step_no 可有多条事件，不做唯一约束",
    )
    event_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    node: Mapped[str | None] = mapped_column(String(32))
    tool: Mapped[str | None] = mapped_column(String(200))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
