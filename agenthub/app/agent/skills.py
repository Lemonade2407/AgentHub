"""V2 Skill 解析与注入。归属：A（Agent Runtime）。

V2 的 Agent 定义由「基座 Prompt」升级为「基座 Prompt + 多个 Skill」。本模块只做纯计算：

- 按 `order_no` 组装最终 system prompt；
- 渲染 `{{param}}` 占位符并校验必填参数；
- 合并「Agent 显式绑定工具 ∪ Skill 绑定工具」，按 `qualified_name` 去重；
- 记录缺失工具与截断情况，供 Runtime 写入 Trace。

本模块不访问数据库：Skill 及其工具由 D / B 解析为 `SkillDefinition` 后传入。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.mcp.schemas import ToolDefinition

# 单个 Skill 片段低于该长度就不再硬塞进 Prompt，整体丢弃并告警
MIN_SKILL_FRAGMENT_CHARS = 120
# 默认字符预算（未提供模型上下文窗口时使用）
DEFAULT_PROMPT_BUDGET_CHARS = 12_000
# 契约 V2：上下文窗口按 60% 预留给 system prompt
CONTEXT_BUDGET_RATIO = 0.6

_PARAM_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class SkillValidationError(ValueError):
    """Skill 参数不合法，Runtime 会转为 `SKILL_INVALID_PARAMS` 失败。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        skill_slug: str | None = None,
        param: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.skill_slug = skill_slug
        self.param = param


class SkillParameter(BaseModel):
    """Skill 的参数契约（JSON Schema 子集的运行时形态）。"""

    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    type: Literal["string", "number", "boolean"] = "string"
    required: bool = False
    default: Any = None


class SkillToolRef(BaseModel):
    """Skill 对某个 Tool 的引用。

    `tool=None` 表示 D/B 在解析时没有找到该 Tool：可能是未注册、被禁用或跨用户不可见。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="ignore")

    qualified_name: str
    required: bool = True
    tool: ToolDefinition | None = None


class SkillDefinition(BaseModel):
    """一次 Run 中参与注入的 Skill 快照。

    `values` 来自 `agent_skill.params`，用于覆盖 `SkillParameter.default`。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="ignore")

    id: int | None = None
    slug: str
    name: str
    version: str = "1.0.0"
    instructions: str = ""
    parameters: list[SkillParameter] = Field(default_factory=list)
    values: dict[str, Any] = Field(default_factory=dict)
    tools: list[SkillToolRef] = Field(default_factory=list)
    enabled: bool = True
    order_no: int = 0


class InjectedSkill(BaseModel):
    """写入 Trace 的「本次生效的 Skill」。"""

    skill_id: int | None = None
    slug: str
    name: str
    version: str
    order_no: int
    prompt_chars: int = 0
    tools: list[str] = Field(default_factory=list)


class MissingSkillTool(BaseModel):
    """Skill 引用但当前不可用的 Tool。"""

    skill_slug: str
    qualified_name: str
    required: bool


class SkillPlan(BaseModel):
    """Skill 解析结果，Runtime 直接消费。"""

    system_prompt: str
    tools: list[ToolDefinition] = Field(default_factory=list)
    injected: list[InjectedSkill] = Field(default_factory=list)
    missing_tools: list[MissingSkillTool] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    truncated: bool = False
    prompt_chars: int = 0
    budget_chars: int = DEFAULT_PROMPT_BUDGET_CHARS

    @property
    def missing_required_tools(self) -> list[MissingSkillTool]:
        return [item for item in self.missing_tools if item.required]


class SkillResolver:
    """把 Agent 基座 Prompt 与 Skill 列表合成为一次 Run 的执行输入。

    纯函数式：同一输入必得同一输出，便于单测与复现。
    """

    def __init__(self, prompt_budget_chars: int = DEFAULT_PROMPT_BUDGET_CHARS) -> None:
        if prompt_budget_chars <= 0:
            raise ValueError("prompt_budget_chars 必须为正整数")
        self._budget = prompt_budget_chars

    @staticmethod
    def budget_from_context_window(context_window: int | None) -> int:
        """按模型上下文窗口推算字符预算；未知窗口时回落到默认值。"""
        if not context_window or context_window <= 0:
            return DEFAULT_PROMPT_BUDGET_CHARS
        return max(2_000, int(context_window * CONTEXT_BUDGET_RATIO))

    def resolve(
        self,
        *,
        agent_system_prompt: str,
        skills: Sequence[SkillDefinition] = (),
        bound_tools: Sequence[ToolDefinition] = (),
        prompt_budget_chars: int | None = None,
    ) -> SkillPlan:
        budget = prompt_budget_chars or self._budget
        ordered = sorted(
            (skill for skill in skills if skill.enabled),
            key=lambda skill: (skill.order_no, skill.slug),
        )

        # 无 Skill：保持 V1 行为，Prompt 与工具集合原样返回
        if not ordered:
            tools = _dedupe_tools(bound_tools)
            return SkillPlan(
                system_prompt=agent_system_prompt,
                tools=tools,
                prompt_chars=len(agent_system_prompt or ""),
                budget_chars=budget,
            )

        warnings: list[str] = []
        missing: list[MissingSkillTool] = []
        injected: list[InjectedSkill] = []
        merged_tools = _dedupe_tools(bound_tools)

        parts: list[str] = [agent_system_prompt] if agent_system_prompt else []
        used = len(agent_system_prompt or "")
        truncated = False
        dropped: list[str] = []

        def accept(
            skill: SkillDefinition,
            *,
            prompt_chars: int,
            contributed: list[str],
            pending_missing: list[MissingSkillTool],
            local_warnings: list[str],
        ) -> None:
            """确认某个 Skill 生效后才合并它的工具、缺失项与警告。"""
            nonlocal merged_tools
            merged_tools = _dedupe_tools(
                [*merged_tools, *(ref.tool for ref in skill.tools if ref.tool is not None)]
            )
            missing.extend(pending_missing)
            warnings.extend(local_warnings)
            injected.append(
                InjectedSkill(
                    skill_id=skill.id,
                    slug=skill.slug,
                    name=skill.name,
                    version=skill.version,
                    order_no=skill.order_no,
                    prompt_chars=prompt_chars,
                    tools=contributed,
                )
            )

        for index, skill in enumerate(ordered):
            local_warnings: list[str] = []
            rendered = _render_instructions(skill, local_warnings)
            contributed = [ref.qualified_name for ref in skill.tools if ref.tool is not None]
            pending_missing = [
                MissingSkillTool(
                    skill_slug=skill.slug,
                    qualified_name=ref.qualified_name,
                    required=ref.required,
                )
                for ref in skill.tools
                if ref.tool is None
            ]
            for item in pending_missing:
                if not item.required:
                    local_warnings.append(
                        f"SKILL_TOOL_MISSING_OPTIONAL:{skill.slug}:{item.qualified_name}"
                    )

            # 纯工具型 Skill：没有指令文本，不占 Prompt 预算
            if not rendered.strip():
                accept(
                    skill,
                    prompt_chars=0,
                    contributed=contributed,
                    pending_missing=pending_missing,
                    local_warnings=local_warnings,
                )
                continue

            header = f"## Skill: {skill.name} (v{skill.version})"
            separator = "\n\n" if parts else ""
            fragment = f"{separator}{header}\n\n{rendered}"
            remaining = budget - used

            if len(fragment) <= remaining:
                parts.append(fragment)
                used += len(fragment)
                accept(
                    skill,
                    prompt_chars=len(fragment),
                    contributed=contributed,
                    pending_missing=pending_missing,
                    local_warnings=local_warnings,
                )
                continue

            # 装不下：优先截断当前 Skill，之后的全部丢弃（顺序即优先级）
            banner = "\n...(truncated)"
            available = remaining - len(separator) - len(header) - 2 - len(banner)
            if available >= MIN_SKILL_FRAGMENT_CHARS:
                clipped = f"{separator}{header}\n\n{rendered[:available]}{banner}"
                parts.append(clipped)
                used += len(clipped)
                local_warnings.append(f"SKILL_PROMPT_TRUNCATED:{skill.slug}")
                accept(
                    skill,
                    prompt_chars=len(clipped),
                    contributed=contributed,
                    pending_missing=pending_missing,
                    local_warnings=local_warnings,
                )
            else:
                warnings.append(f"SKILL_PROMPT_DROPPED:{skill.slug}")
            truncated = True
            dropped = [item.slug for item in ordered[index + 1 :]]
            break

        if dropped:
            warnings.append("SKILL_PROMPT_DROPPED_LATER:" + ",".join(dropped))

        system_prompt = "".join(parts)
        return SkillPlan(
            system_prompt=system_prompt,
            tools=merged_tools,
            injected=injected,
            missing_tools=missing,
            warnings=warnings,
            truncated=truncated,
            prompt_chars=len(system_prompt),
            budget_chars=budget,
        )


def _render_instructions(skill: SkillDefinition, warnings: list[str]) -> str:
    values = _parameter_values(skill, warnings)
    used: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        used.add(name)
        if name not in values:
            return match.group(0)
        return str(values[name])

    text = _PARAM_RE.sub(replace, skill.instructions or "")
    declared = {param.name for param in skill.parameters}
    for name in sorted(used - declared):
        warnings.append(f"SKILL_UNKNOWN_PLACEHOLDER:{skill.slug}:{name}")
    return text


def _parameter_values(skill: SkillDefinition, warnings: list[str]) -> dict[str, Any]:
    declared = {param.name: param for param in skill.parameters}
    values: dict[str, Any] = {}

    for param in skill.parameters:
        if param.name in skill.values:
            values[param.name] = _coerce(param, skill.values[param.name], skill)
        elif param.default is not None:
            values[param.name] = _coerce(param, param.default, skill)
        elif param.required:
            raise SkillValidationError(
                "SKILL_INVALID_PARAMS",
                f"Skill「{skill.name}」缺少必填参数：{param.name}",
                skill_slug=skill.slug,
                param=param.name,
            )
        else:
            values[param.name] = ""

    for name in skill.values:
        if name not in declared:
            warnings.append(f"SKILL_UNKNOWN_PARAM:{skill.slug}:{name}")
    return values


def _coerce(param: SkillParameter, value: Any, skill: SkillDefinition) -> Any:
    if param.type == "string":
        return value if isinstance(value, str) else str(value)
    if param.type == "number":
        if isinstance(value, bool):
            raise _invalid_param(skill, param)
        if isinstance(value, (int, float)):
            return value
        try:
            return float(value)
        except (TypeError, ValueError):
            raise _invalid_param(skill, param) from None
    if param.type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
        raise _invalid_param(skill, param)
    raise _invalid_param(skill, param)


def _invalid_param(skill: SkillDefinition, param: SkillParameter) -> SkillValidationError:
    return SkillValidationError(
        "SKILL_INVALID_PARAMS",
        f"Skill「{skill.name}」参数 {param.name} 不是合法的 {param.type}",
        skill_slug=skill.slug,
        param=param.name,
    )


def _dedupe_tools(tools: Sequence[ToolDefinition]) -> list[ToolDefinition]:
    """按 `qualified_name` 去重，保留首次出现的顺序（显式绑定优先、Skill 按 order_no）。"""
    seen: set[str] = set()
    result: list[ToolDefinition] = []
    for tool in tools:
        if tool is None or tool.qualified_name in seen:
            continue
        seen.add(tool.qualified_name)
        result.append(tool)
    return result
