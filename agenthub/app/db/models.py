"""六张表的 SQLAlchemy 模型。数据库设计文档 §6。归属：D（Platform Backend）。

字段类型、约束与索引与 DDL 一一对应；`create_all` 仅用于本地开发，
生产环境应以 Alembic 迁移为准（数据库设计文档 §7.1）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agent"
    __table_args__ = (
        CheckConstraint("max_steps BETWEEN 1 AND 20", name="ck_agent_max_steps"),
        Index("idx_agent_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512))
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    max_steps: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=8)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class McpServer(Base):
    __tablename__ = "mcp_server"
    __table_args__ = (
        UniqueConstraint("name", name="uq_mcp_server_name"),
        CheckConstraint(
            "transport IN ('streamable_http', 'stdio')", name="ck_mcp_server_transport"
        ),
        CheckConstraint(
            "status IN ('UNKNOWN', 'CONNECTED', 'ERROR')", name="ck_mcp_server_status"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(512), nullable=False)
    transport: Mapped[str] = mapped_column(String(32), nullable=False, default="streamable_http")
    description: Mapped[str | None] = mapped_column(String(512))
    headers: Mapped[dict | None] = mapped_column(JSONB)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="UNKNOWN")
    last_error: Mapped[str | None] = mapped_column(String(512))
    last_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class McpTool(Base):
    __tablename__ = "mcp_tool"
    __table_args__ = (
        UniqueConstraint("server_id", "remote_name", name="uq_mcp_tool_server_remote"),
        UniqueConstraint("qualified_name", name="uq_mcp_tool_qualified_name"),
        CheckConstraint(
            "risk_level IN ('READ_ONLY', 'LOW_RISK', 'WRITE', 'HIGH_RISK')",
            name="ck_mcp_tool_risk_level",
        ),
        Index("idx_mcp_tool_server_enabled", "server_id", "enabled"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    server_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("mcp_server.id", ondelete="CASCADE"), nullable=False
    )
    remote_name: Mapped[str] = mapped_column(String(128), nullable=False)
    qualified_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="LOW_RISK")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class AgentTool(Base):
    __tablename__ = "agent_tool"

    agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agent.id", ondelete="CASCADE"), primary_key=True
    )
    tool_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("mcp_tool.id", ondelete="CASCADE"), primary_key=True
    )


class AgentRun(Base):
    __tablename__ = "agent_run"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCESS', 'PARTIAL', 'FAILED', 'CANCELLED')",
            name="ck_agent_run_status",
        ),
        CheckConstraint(
            "stop_reason IS NULL OR stop_reason IN ('FINISHED', 'MAX_STEPS', 'MODEL_ERROR', "
            "'TOOL_ERROR', 'INTERNAL_ERROR', 'CANCELLED')",
            name="ck_agent_run_stop_reason",
        ),
        CheckConstraint("max_steps BETWEEN 1 AND 20", name="ck_agent_run_max_steps"),
        Index("idx_agent_run_agent_id_created_at", "agent_id", "created_at"),
        Index("idx_agent_run_status_created_at", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agent.id", ondelete="RESTRICT"), nullable=False
    )
    thread_id: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    stop_reason: Mapped[str | None] = mapped_column(String(16))
    input: Mapped[str] = mapped_column(Text, nullable=False)
    output: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(String(512))
    max_steps: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentStep(Base):
    __tablename__ = "agent_step"
    __table_args__ = (
        CheckConstraint("step_no >= 0", name="ck_agent_step_step_no"),
        CheckConstraint(
            "node IS NULL OR node IN ('model_node', 'tools_node')", name="ck_agent_step_node"
        ),
        Index("idx_agent_step_run_step_no", "run_id", "step_no", "id"),
        Index("idx_agent_step_run_id_id", "run_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("agent_run.id", ondelete="CASCADE"), nullable=False
    )
    step_no: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    node: Mapped[str | None] = mapped_column(String(32))
    tool: Mapped[str | None] = mapped_column(String(200))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
