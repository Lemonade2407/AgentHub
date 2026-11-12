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
        # V2：列表按 owner 过滤 + created_at 倒序（替换 V1 全表扫描路径）
        Index(
            "idx_agent_owner_created_active",
            "owner_id",
            text("created_at DESC"),
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
    # ---- V2 新增（修改意见 §3.2，过渡期兼容）----
    # 资源归属；local 模式下统一指向内置 local 用户。历史数据由 0002 迁移回填
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("app_user.id"),
    )
    # 引用的模型 API；NULL 表示 V1 legacy Agent，继续走环境变量路径
    model_api_id: Mapped[int | None] = mapped_column(
        BigInteger,
        # 被引用时禁止物理删除 Model API，只允许 enabled=false
        ForeignKey("model_api.id", ondelete="RESTRICT"),
    )
    # 该 API 下的具体模型名；读路径优先 model_api_id + model_key，写路径双写 model
    model_key: Mapped[str | None] = mapped_column(String(128))


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
