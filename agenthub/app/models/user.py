"""`app_user` 模型（修改意见文档 §3.2，DB 设计文档 v2.0）。"""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, Identity, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import UserStatus
from app.models.base import Base, TimestampMixin, in_clause


class AppUser(TimestampMixin, Base):
    """平台账号。V2 最小账号体系：不做角色与权限矩阵，资源按 `owner_id` 隔离。"""

    __tablename__ = "app_user"
    __table_args__ = (
        CheckConstraint(in_clause("status", UserStatus), name="status"),
        {"comment": "平台账号（V2 最小账号体系）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    email: Mapped[str] = mapped_column(String(128), unique=True)
    display_name: Mapped[str] = mapped_column(String(64))
    # 内置 local 用户为占位串 '!locked'，任何密码都不会命中
    password_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), server_default=UserStatus.ACTIVE.value)
