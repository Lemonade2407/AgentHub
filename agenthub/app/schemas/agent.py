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
