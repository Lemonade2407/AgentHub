"""契约 §3.1 / §3.4 —— Agent & Run DTO。

冻结来源：AgentHub_接口契约文档.md §3.1、§3.4。
Schema 配置：Pydantic v2 用 `ConfigDict(from_attributes=True)` 替代旧版 `orm_mode`。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import RunStatus, StopReason


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)
    model: str = Field(min_length=1, max_length=128)
    system_prompt: str = Field(default="", max_length=8000)
    max_steps: int = Field(default=8, ge=1, le=20)
    enabled: bool = True
    tool_ids: list[int] = Field(default_factory=list)


class AgentUpdate(BaseModel):
    """PUT 部分更新；未传字段保持不变。"""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    system_prompt: str | None = Field(default=None, max_length=8000)
    max_steps: int | None = Field(default=None, ge=1, le=20)
    enabled: bool | None = None


class AgentToolBind(BaseModel):
    """PUT /api/agents/{id}/tools 全量覆盖。"""

    tool_ids: list[int]


class AgentRead(BaseModel):
    """Agent 响应对象；ORM 实体直接 `.model_validate(orm)`。"""

    model_config = ConfigDict(from_attributes=True)

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


# ---------- §3.4 Run ----------


class RunCreateRequest(BaseModel):
    input: str = Field(min_length=1, max_length=8000)
    # Run 级唯一可覆盖项（契约 §3.4 "Run 级覆盖范围"）
    max_steps: int | None = Field(default=None, ge=1, le=20)
    stream: bool = False


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: int
    thread_id: str
    status: RunStatus
    stop_reason: StopReason | None = None
    input: str
    output: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    max_steps: int
    llm_calls: int = 0
    tool_calls: int = 0
    step_count: int = 0
    duration_ms: int | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
