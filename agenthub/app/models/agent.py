"""`agent` / `agent_tool` 模型（数据库设计文档 §3.1、§3.4）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Agent(TimestampMixin, Base):
    """Agent 持久化配置（AgentDefinition）。"""

    __tablename__ = "agent"
    __table_args__ = (
        CheckConstraint("max_steps BETWEEN 1 AND 20", name="max_steps"),
        Index(
            "idx_agent_created_at_active",
            "created_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"comment": "Agent 持久化配置（AgentDefinition）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # 不做唯一约束：允许重名，用 id 区分（§9 D-DB2）
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(String(512))
    model: Mapped[str] = mapped_column(String(128))
    system_prompt: Mapped[str] = mapped_column(Text, server_default="")
    max_steps: Mapped[int] = mapped_column(SmallInteger, server_default=text("8"))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentTool(Base):
    """Agent 与 Tool 的多对多绑定关系；主键天然防重。"""

    __tablename__ = "agent_tool"
    __table_args__ = (
        Index("idx_agent_tool_tool_id", "tool_id"),
        {"comment": "Agent 与 Tool 的多对多绑定关系"},
    )

    agent_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("agent.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tool_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("mcp_tool.id", ondelete="CASCADE"),
        primary_key=True,
    )
