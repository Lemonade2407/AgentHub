"""Agent Center 预检与安装 DTO（修改意见文档 §5.5 / §5.6，Contract v2.0）。

归属：D（Platform Backend）+ B（依赖解析）。约定：
- 预检只读，不创建任何数据；
- `confirm_missing=true` 时允许跳过缺失依赖继续安装；
- 安装结果返回“仍需处理的事项”，由前端引导用户补齐。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MissingSkillRead(BaseModel):
    """快照引用但安装者本地无法匹配的 Skill。"""

    slug: str
    version: str = "1.0.0"
    params: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    reason: str


class MissingToolRead(BaseModel):
    """快照引用但本地 Tool Registry 无法匹配的 Tool。"""

    server_name: str
    remote_name: str
    required: bool = True
    reason: str


class SuggestedModelRead(BaseModel):
    provider: str
    model_key: str


class PrecheckRead(BaseModel):
    """`POST /api/agent-center/{id}/precheck` 的响应。"""

    publication_id: int
    title: str
    can_install: bool
    already_installed: bool = False
    installed_agent_id: int | None = None
    resolved_skills: int = 0
    resolved_tools: int = 0
    missing_skills: list[MissingSkillRead] = Field(default_factory=list)
    missing_tools: list[MissingToolRead] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    suggested_model: SuggestedModelRead | None = None


class InstallRequest(BaseModel):
    """安装请求；`confirm_missing=true` 表示跳过缺失依赖继续安装。"""

    confirm_missing: bool = False


class InstallRead(BaseModel):
    """安装结果：新 Agent 与仍需处理的事项。"""

    publication_id: int
    agent_id: int
    installed_skill_ids: list[int] = Field(default_factory=list)
    installed_tool_ids: list[int] = Field(default_factory=list)
    missing_skills: list[MissingSkillRead] = Field(default_factory=list)
    missing_tools: list[MissingToolRead] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
