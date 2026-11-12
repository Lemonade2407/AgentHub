"""`agent_publication` / `publication_like` / `publication_install` 模型
（修改意见文档 §5.3，DB 设计文档 v2.0）。"""

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
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import PublicationStatus, SkillCategory
from app.models.base import Base, TimestampMixin, in_clause


class AgentPublication(TimestampMixin, Base):
    """Agent 的不可变发布快照，Agent Center 的陈列单位。"""

    __tablename__ = "agent_publication"
    __table_args__ = (
        # 同一 Agent 同一版本只允许一条发布记录；重发需升版本
        UniqueConstraint("owner_id", "source_agent_id", "version"),
        CheckConstraint(in_clause("status", PublicationStatus), name="status"),
        CheckConstraint(in_clause("category", SkillCategory), name="category"),
        Index(
            "idx_publication_feed",
            "status",
            "category",
            text("published_at DESC"),
        ),
        Index("idx_agent_publication_owner_id", "owner_id"),
        {"comment": "Agent 发布快照（V2 Agent Center）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("app_user.id", ondelete="CASCADE"),
    )
    # 源 Agent 删除后发布保留，置 NULL
    source_agent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("agent.id", ondelete="SET NULL"),
    )
    title: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(String(512), server_default="")
    category: Mapped[str] = mapped_column(
        String(32), server_default=SkillCategory.GENERAL.value
    )
    version: Mapped[str] = mapped_column(String(16), server_default="1.0.0")
    status: Mapped[str] = mapped_column(
        String(16), server_default=PublicationStatus.PUBLISHED.value
    )
    # 脱敏后的不可变快照（结构冻结于契约 §5.4 / snapshot.py 白名单校验）
    snapshot: Mapped[dict] = mapped_column(
        JSONB,
        comment="脱敏后的不可变发布快照，禁止包含密钥 / headers / owner_id",
    )
    install_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    like_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PublicationLike(Base):
    """点赞关系；主键天然保证同一用户只能点一次。"""

    __tablename__ = "publication_like"
    __table_args__ = (
        Index("idx_publication_like_user_id", "user_id"),
        {"comment": "Publication 点赞关系（V2）"},
    )

    publication_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("agent_publication.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("app_user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class PublicationInstall(Base):
    """安装记录：谁把哪个 Publication 复制成了哪个本地 Agent。"""

    __tablename__ = "publication_install"
    __table_args__ = (
        # 重复安装返回 409 ALREADY_INSTALLED，由唯一约束兜底（§5.5 / US-M3-4）
        UniqueConstraint("publication_id", "installer_id"),
        Index("idx_publication_install_installer_id", "installer_id"),
        {"comment": "Publication 安装记录（V2）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    publication_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("agent_publication.id", ondelete="CASCADE"),
    )
    installer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("app_user.id", ondelete="CASCADE"),
    )
    # 本地副本删除后安装记录保留，置 NULL
    installed_agent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("agent.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
