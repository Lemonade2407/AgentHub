"""Skill / Agent Skill 挂载 DTO（修改意见文档 §4.5，Contract v2.0）。

约定：
- Skill 的 `input_schema` 是 JSON Schema 子集：`{"type":"object","properties":{...},"required":[...]}`；
- 工具绑定以 `tool_id + required` 表达，`required=false` 的工具缺失时只记录 Trace；
- Agent 挂载以 `skill_id + order_no + enabled + params` 表达，`params` 覆盖 Skill 默认值。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.enums import SkillCategory, SkillStatus, SkillVisibility

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]*$"


class SkillToolBind(BaseModel):
    """创建 / 更新 Skill 时的工具绑定。"""

    tool_id: int
    required: bool = True


class SkillCreate(BaseModel):
    """创建 Skill。`slug` 缺省时由后端根据名称生成。"""

    name: str = Field(min_length=1, max_length=64)
    slug: str | None = Field(default=None, max_length=80, pattern=SLUG_PATTERN)
    summary: str = Field(default="", max_length=512)
    category: SkillCategory = SkillCategory.GENERAL
    icon: str | None = Field(default=None, max_length=64)
    version: str = Field(default="1.0.0", min_length=1, max_length=16)
    visibility: SkillVisibility = SkillVisibility.PRIVATE
    instructions: str = Field(default="", max_length=20000)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=20)
    tools: list[SkillToolBind] = Field(default_factory=list)


class SkillUpdate(BaseModel):
    """部分更新 Skill：未传字段保持不变；`tools` 传入时全量覆盖。"""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    slug: str | None = Field(default=None, max_length=80, pattern=SLUG_PATTERN)
    summary: str | None = Field(default=None, max_length=512)
    category: SkillCategory | None = None
    icon: str | None = Field(default=None, max_length=64)
    version: str | None = Field(default=None, min_length=1, max_length=16)
    visibility: SkillVisibility | None = None
    instructions: str | None = Field(default=None, max_length=20000)
    input_schema: dict[str, Any] | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    tools: list[SkillToolBind] | None = None


class SkillToolRead(BaseModel):
    """Skill 绑定的一条 Tool（含当前可用状态，供前端区分只读标签）。"""

    tool_id: int
    qualified_name: str
    server_name: str
    description: str = ""
    required: bool = True
    enabled: bool = True


class SkillRead(BaseModel):
    """Skill 响应对象。"""

    id: int
    owner_id: int
    owner_display_name: str | None = None
    name: str
    slug: str
    summary: str = ""
    category: SkillCategory = SkillCategory.GENERAL
    icon: str | None = None
    version: str = "1.0.0"
    visibility: SkillVisibility = SkillVisibility.PRIVATE
    status: SkillStatus = SkillStatus.DRAFT
    instructions: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    install_count: int = 0
    like_count: int = 0
    tools: list[SkillToolRead] = Field(default_factory=list)
    owned: bool = False
    created_at: datetime
    updated_at: datetime


class AgentSkillBind(BaseModel):
    """Agent 挂载一个 Skill 的声明。"""

    skill_id: int
    order_no: int = Field(default=0, ge=0, le=32767)
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)


class AgentSkillBindRequest(BaseModel):
    """全量覆盖 Agent 的 Skill 挂载。"""

    skills: list[AgentSkillBind] = Field(default_factory=list)


class AgentSkillRead(BaseModel):
    """Agent 详情中的 Skill 列表项。"""

    skill_id: int
    name: str
    slug: str
    version: str
    status: SkillStatus
    visibility: SkillVisibility
    order_no: int
    enabled: bool
    params: dict[str, Any] = Field(default_factory=dict)
    tools: list[SkillToolRead] = Field(default_factory=list)


class SkillExportTool(BaseModel):
    qualified_name: str
    server_name: str
    required: bool = True


class SkillExportPayload(BaseModel):
    name: str
    slug: str
    summary: str = ""
    category: SkillCategory
    icon: str | None = None
    version: str
    instructions: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    tools: list[SkillExportTool] = Field(default_factory=list)


class SkillExport(BaseModel):
    """Skill 导出 JSON：只含可移植定义，不含 owner_id / 计数等本地信息。"""

    schema_version: int = 1
    exported_at: datetime
    skill: SkillExportPayload
