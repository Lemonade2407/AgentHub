"""ORM 基类与全局命名约定（数据库设计文档 §1.1）。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: 约束 / 索引命名规则；Alembic autogenerate 依赖它产出可回滚的稳定名称。
NAMING_CONVENTION = {
    "ix": "idx_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """`created_at` / `updated_at`。

    `updated_at` 由应用层 `onupdate` 维护，不建触发器（§9 D-DB5）。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


def in_clause(column: str, values: Iterable[StrEnum | str]) -> str:
    """生成 CHECK 约束里的 `column IN ('A', 'B')` 片段。

    取值来自 `app/core/enums.py`（契约 §2 冻结枚举），避免模型与枚举各自维护。
    """
    literals = ", ".join(f"'{getattr(v, 'value', v)}'" for v in values)
    return f"{column} IN ({literals})"
