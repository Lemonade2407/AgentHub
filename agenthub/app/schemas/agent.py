"""契约 §3.1 冻结 DTO。归属：D（Platform Backend）。

Agent Runtime 只读取 `model` / `system_prompt` / `max_steps` / `enabled` / `tool_ids`，
不读写数据库，因此不持有 ORM 实体。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AgentRead(BaseModel):
    """Agent 响应对象。"""

    id: int
    name: str
    description: str | None = None
    model: str
    system_prompt: str = ""
    max_steps: int = Field(default=8, ge=1, le=20)
    enabled: bool = True
    tool_ids: list[int] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AgentCreate(BaseModel):
    """Agent 创建请求。"""

    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)
    model: str = Field(min_length=1, max_length=128)
    system_prompt: str = Field(default="", max_length=8000)
    max_steps: int = Field(default=8, ge=1, le=20)
    enabled: bool = True
    tool_ids: list[int] = Field(default_factory=list)


class AgentUpdate(BaseModel):
    """Agent 部分更新请求：未传字段保持不变。"""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    system_prompt: str | None = Field(default=None, max_length=8000)
    max_steps: int | None = Field(default=None, ge=1, le=20)
    enabled: bool | None = None


class AgentToolBind(BaseModel):
    """全量覆盖 Agent 的工具绑定。"""

    tool_ids: list[int] = Field(default_factory=list)
