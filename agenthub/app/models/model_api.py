"""`model_api` / `model_api_model` 模型（修改意见文档 §3.2，DB 设计文档 v2.0）。"""

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
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ModelProvider
from app.models.base import Base, TimestampMixin, in_clause


class ModelApi(TimestampMixin, Base):
    """用户级模型接入配置。`api_key` 以 Fernet 密文存储，任何接口不回显。"""

    __tablename__ = "model_api"
    __table_args__ = (
        UniqueConstraint("owner_id", "name"),
        CheckConstraint(in_clause("provider", ModelProvider), name="provider"),
        # 每个用户至多一条默认 Model API（部分唯一索引，DB 层兜底）
        Index(
            "uq_model_api_owner_default",
            "owner_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
        Index("idx_model_api_owner_id", "owner_id"),
        {"comment": "用户级模型接入配置（V2）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("app_user.id", ondelete="CASCADE"),
    )
    name: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    base_url: Mapped[str] = mapped_column(String(512))
    # Fernet 密文；明文只存在于请求入参与解密后的内存中（§3.5）
    api_key_cipher: Mapped[str] = mapped_column(
        Text,
        comment="Fernet 密文，禁止明文入库、禁止回显",
    )
    # 仅密钥末 4 位，供界面展示 `****abcd`；无法反推原 Key
    api_key_hint: Mapped[str | None] = mapped_column(String(16))
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_error: Mapped[str | None] = mapped_column(String(512))


class ModelApiModel(Base):
    """某条 Model API 下用户勾选可用的模型清单。"""

    __tablename__ = "model_api_model"
    __table_args__ = (
        UniqueConstraint("model_api_id", "model_key"),
        # 每条 Model API 至多一个默认模型
        Index(
            "uq_model_api_model_default",
            "model_api_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
        {"comment": "Model API 下的可用模型清单（V2）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    model_api_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("model_api.id", ondelete="CASCADE"),
    )
    # 传给上游的 model 名，如 deepseek-chat
    model_key: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(128))
    # {"tool_call": true, "vision": false, "context_window": 64000}
    capabilities: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
