"""`mcp_server` / `mcp_tool` 模型（数据库设计文档 §3.2、§3.3）。"""

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import McpServerStatus, RiskLevel, TransportType
from app.models.base import Base, TimestampMixin, in_clause


class McpServer(TimestampMixin, Base):
    """MCP Server 注册信息。"""

    __tablename__ = "mcp_server"
    __table_args__ = (
        UniqueConstraint("name"),
        CheckConstraint(in_clause("transport", TransportType), name="transport"),
        CheckConstraint(in_clause("status", McpServerStatus), name="status"),
        {"comment": "MCP Server 注册信息"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # 注册后不可修改：它派生 server_slug，进而决定 mcp_tool.qualified_name（§9 D-DB6）
    name: Mapped[str] = mapped_column(String(64))
    endpoint: Mapped[str] = mapped_column(String(512))
    transport: Mapped[str] = mapped_column(
        String(32), server_default=TransportType.STREAMABLE_HTTP.value
    )
    description: Mapped[str | None] = mapped_column(String(512))
    headers: Mapped[dict | None] = mapped_column(
        JSONB,
        comment="敏感字段，仅后端读取，任何接口不回传",
    )
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    status: Mapped[str] = mapped_column(
        String(16), server_default=McpServerStatus.UNKNOWN.value
    )
    last_error: Mapped[str | None] = mapped_column(String(512))
    last_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class McpTool(TimestampMixin, Base):
    """MCP Tool 元数据（Tool Registry 的存储层）。"""

    __tablename__ = "mcp_tool"
    __table_args__ = (
        UniqueConstraint("server_id", "remote_name"),
        UniqueConstraint("qualified_name"),
        CheckConstraint(in_clause("risk_level", RiskLevel), name="risk_level"),
        Index("idx_mcp_tool_server_enabled", "server_id", "enabled"),
        {"comment": "MCP Tool 元数据（Tool Registry 的存储层）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    server_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("mcp_server.id", ondelete="CASCADE"),
    )
    remote_name: Mapped[str] = mapped_column(String(128))
    qualified_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, server_default="")
    input_schema: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    risk_level: Mapped[str] = mapped_column(
        String(16), server_default=RiskLevel.LOW_RISK.value
    )
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
