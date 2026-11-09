"""create initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-10 21:30:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------- agent ----------
    op.create_table(
        "agent",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("system_prompt", sa.Text(), server_default="", nullable=False),
        sa.Column("max_steps", sa.SmallInteger(), server_default=sa.text("8"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent"),
        sa.CheckConstraint("max_steps BETWEEN 1 AND 20", name="max_steps"),
        comment="Agent 持久化配置（AgentDefinition）",
    )
    op.create_index(
        "idx_agent_created_at_active",
        "agent",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ---------- mcp_server ----------
    op.create_table(
        "mcp_server",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("endpoint", sa.String(length=512), nullable=False),
        sa.Column(
            "transport",
            sa.String(length=32),
            server_default="streamable_http",
            nullable=False,
        ),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column(
            "headers",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="敏感字段，仅后端读取，任何接口不回传",
        ),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="UNKNOWN", nullable=False),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.Column("last_discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mcp_server"),
        sa.UniqueConstraint("name", name="uq_mcp_server_name"),
        sa.CheckConstraint(
            "transport IN ('streamable_http', 'stdio')",
            name="transport",
        ),
        sa.CheckConstraint(
            "status IN ('UNKNOWN', 'CONNECTED', 'ERROR')",
            name="status",
        ),
        comment="MCP Server 注册信息",
    )

    # ---------- mcp_tool ----------
    op.create_table(
        "mcp_tool",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("remote_name", sa.String(length=128), nullable=False),
        sa.Column("qualified_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "input_schema",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "risk_level",
            sa.String(length=16),
            server_default="LOW_RISK",
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mcp_tool"),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["mcp_server.id"],
            name="fk_mcp_tool_server_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "server_id", "remote_name", name="uq_mcp_tool_server_id_remote_name"
        ),
        sa.UniqueConstraint("qualified_name", name="uq_mcp_tool_qualified_name"),
        sa.CheckConstraint(
            "risk_level IN ('READ_ONLY', 'LOW_RISK', 'WRITE', 'HIGH_RISK')",
            name="risk_level",
        ),
        comment="MCP Tool 元数据（Tool Registry 的存储层）",
    )
    op.create_index(
        "idx_mcp_tool_server_enabled", "mcp_tool", ["server_id", "enabled"], unique=False
    )

    # ---------- agent_tool ----------
    op.create_table(
        "agent_tool",
        sa.Column("agent_id", sa.BigInteger(), nullable=False),
        sa.Column("tool_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("agent_id", "tool_id", name="pk_agent_tool"),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent.id"],
            name="fk_agent_tool_agent_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tool_id"],
            ["mcp_tool.id"],
            name="fk_agent_tool_tool_id",
            ondelete="CASCADE",
        ),
        comment="Agent 与 Tool 的多对多绑定关系",
    )
    op.create_index("idx_agent_tool_tool_id", "agent_tool", ["tool_id"], unique=False)

    # ---------- agent_run ----------
    op.create_table(
        "agent_run",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.BigInteger(), nullable=False),
        sa.Column("thread_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("stop_reason", sa.String(length=16), nullable=True),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column(
            "max_steps",
            sa.SmallInteger(),
            nullable=False,
            comment="本次 Run 实际生效的 max_steps 快照，用于复现",
        ),
        sa.Column("llm_calls", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tool_calls", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("step_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_agent_run"),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent.id"],
            name="fk_agent_run_agent_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCESS', 'PARTIAL', 'FAILED', 'CANCELLED')",
            name="status",
        ),
        sa.CheckConstraint(
            "stop_reason IS NULL OR stop_reason IN ('FINISHED', 'MAX_STEPS', "
            "'MODEL_ERROR', 'TOOL_ERROR', 'INTERNAL_ERROR', 'CANCELLED')",
            name="stop_reason",
        ),
        sa.CheckConstraint("max_steps BETWEEN 1 AND 20", name="max_steps"),
        comment="一次 Agent 运行记录",
    )
    op.create_index(
        "idx_agent_run_agent_id_created_at",
        "agent_run",
        ["agent_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "idx_agent_run_status_created_at",
        "agent_run",
        ["status", sa.text("created_at DESC")],
        unique=False,
    )

    # ---------- agent_step ----------
    op.create_table(
        "agent_step",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column(
            "step_no",
            sa.Integer(),
            nullable=False,
            comment="图执行步序号；0 为 Run 级事件；同一 step_no 可有多条事件，不做唯一约束",
        ),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("node", sa.String(length=32), nullable=True),
        sa.Column("tool", sa.String(length=200), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "payload",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_step"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_run.id"],
            name="fk_agent_step_run_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "event_type IN ('RUN_STARTED', 'LLM_STARTED', 'LLM_FINISHED', "
            "'TOOL_CANDIDATES', 'TOOL_CALL_STARTED', 'TOOL_CALL_FINISHED', "
            "'STATE_UPDATED', 'RUN_FINISHED', 'RUN_FAILED')",
            name="event_type",
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'SUCCESS', 'FAILED', 'SKIPPED')",
            name="status",
        ),
        sa.CheckConstraint(
            "node IS NULL OR node IN ('model_node', 'tools_node')",
            name="node",
        ),
        sa.CheckConstraint("step_no >= 0", name="step_no"),
        comment="Trace / 执行步骤；id 同时作为 SSE 的事件 id",
    )
    op.create_index(
        "idx_agent_step_run_step_no",
        "agent_step",
        ["run_id", "step_no", "id"],
        unique=False,
    )
    op.create_index("idx_agent_step_run_id_id", "agent_step", ["run_id", "id"], unique=False)


def downgrade() -> None:
    # 反向依赖顺序：step → run → agent_tool → mcp_tool → mcp_server → agent
    op.drop_table("agent_step")
    op.drop_table("agent_run")
    op.drop_table("agent_tool")
    op.drop_table("mcp_tool")
    op.drop_table("mcp_server")
    op.drop_table("agent")
