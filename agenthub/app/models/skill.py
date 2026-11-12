"""`skill` / `skill_tool` / `agent_skill` 模型（修改意见文档 §4.3，DB 设计文档 v2.0）。"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import SkillCategory, SkillStatus, SkillVisibility
from app.models.base import Base, TimestampMixin, in_clause


class Skill(TimestampMixin, Base):
    """可复用能力包：指令片段 + 工具集合 + 参数契约（不含可执行代码）。"""

    __tablename__ = "skill"
    __table_args__ = (
        UniqueConstraint("owner_id", "slug"),
        CheckConstraint(in_clause("visibility", SkillVisibility), name="visibility"),
        CheckConstraint(in_clause("status", SkillStatus), name="status"),
        CheckConstraint(in_clause("category", SkillCategory), name="category"),
        # slug 全网引用标识（快照按 slug+version 匹配）：小写字母数字与连字符
        CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]*$'", name="slug_format"),
        Index("idx_skill_public", "status", "visibility", "category"),
        Index("idx_skill_owner_id", "owner_id"),
        {"comment": "可复用能力包：指令片段 + 工具集合 + 参数契约（V2）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("app_user.id", ondelete="CASCADE"),
    )
    name: Mapped[str] = mapped_column(String(64))
    slug: Mapped[str] = mapped_column(String(80))
    summary: Mapped[str] = mapped_column(String(512), server_default="")
    category: Mapped[str] = mapped_column(
        String(32), server_default=SkillCategory.GENERAL.value
    )
    # 图标名，前端映射，不做图片上传（修改意见 Q7）
    icon: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(16), server_default="1.0.0")
    visibility: Mapped[str] = mapped_column(
        String(16), server_default=SkillVisibility.PRIVATE.value
    )
    status: Mapped[str] = mapped_column(
        String(16), server_default=SkillStatus.DRAFT.value
    )
    # 注入 system prompt 的片段，支持 {{param}} 占位
    instructions: Mapped[str] = mapped_column(Text, server_default="")
    # 参数契约（JSON Schema 子集），运行期仅做字符串替换渲染
    input_schema: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    tags: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    install_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    like_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class SkillTool(Base):
    """Skill 与 MCP Tool 的绑定；`required=false` 的工具缺失时仅记录 Trace。"""

    __tablename__ = "skill_tool"
    __table_args__ = (
        Index("idx_skill_tool_tool_id", "tool_id"),
        {"comment": "Skill 与 MCP Tool 的绑定关系（V2）"},
    )

    skill_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("skill.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tool_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("mcp_tool.id", ondelete="CASCADE"),
        primary_key=True,
    )
    required: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class AgentSkill(Base):
    """Agent 对 Skill 的挂载。`params` 覆盖 Skill 默认参数。"""

    __tablename__ = "agent_skill"
    __table_args__ = (
        Index("idx_agent_skill_skill_id", "skill_id"),
        {"comment": "Agent 与 Skill 的挂载关系（V2）"},
    )

    agent_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("agent.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Skill 被挂载时禁止物理删除（§4.5：DELETE 返回 409 SKILL_IN_USE）
    skill_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("skill.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    # 注入顺序：按 order_no 升序渲染进 system prompt
    order_no: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    params: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
