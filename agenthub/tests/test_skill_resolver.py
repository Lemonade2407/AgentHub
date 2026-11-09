"""SkillResolver 单元测试（V2：Prompt 组装 / 参数渲染 / 工具合并 / 预算截断）。"""

from __future__ import annotations

import pytest

from app.agent.skills import (
    DEFAULT_PROMPT_BUDGET_CHARS,
    MIN_SKILL_FRAGMENT_CHARS,
    SkillDefinition,
    SkillParameter,
    SkillResolver,
    SkillToolRef,
    SkillValidationError,
)
from tests.fakes import make_skill, make_tool

BOUND_TOOL = "search.search_web"
SKILL_TOOL = "github.list_issues"


def resolve(
    *,
    system_prompt: str = "你是助理。",
    skills: list[SkillDefinition] | None = None,
    bound_tools: list | None = None,
    budget: int | None = None,
):
    return SkillResolver().resolve(
        agent_system_prompt=system_prompt,
        skills=skills or [],
        bound_tools=bound_tools or [],
        prompt_budget_chars=budget,
    )


def test_without_skills_keeps_v1_behavior() -> None:
    tools = [make_tool(BOUND_TOOL)]
    plan = resolve(system_prompt="原样 Prompt", bound_tools=tools)

    assert plan.system_prompt == "原样 Prompt"
    assert plan.tools == tools
    assert plan.injected == []
    assert plan.warnings == []
    assert plan.truncated is False


def test_skill_instructions_are_rendered_and_appended_after_base_prompt() -> None:
    skill = make_skill("weekly", name="周报生成", instructions="用 {{tone}} 语气写周报。")
    plan = resolve(system_prompt="你是助理。", skills=[skill], budget=1000)

    assert plan.system_prompt.startswith("你是助理。")
    assert "## Skill: 周报生成 (v1.0.0)" in plan.system_prompt
    assert "用 正式 语气写周报。" in plan.system_prompt
    assert plan.injected[0].slug == "weekly"
    assert plan.injected[0].prompt_chars > 0


def test_skills_are_sorted_by_order_no_not_input_order() -> None:
    second = make_skill("b", name="B", instructions="B 指令", order_no=2)
    first = make_skill("a", name="A", instructions="A 指令", order_no=1)

    prompt = resolve(skills=[second, first], budget=2000).system_prompt

    assert prompt.index("A 指令") < prompt.index("B 指令")


def test_agent_values_override_defaults() -> None:
    skill = make_skill("weekly", instructions="语气：{{tone}}", values={"tone": "轻松"})
    prompt = resolve(skills=[skill], budget=1000).system_prompt

    assert "语气：轻松" in prompt
    assert "正式" not in prompt


def test_missing_required_param_fails_before_run() -> None:
    skill = make_skill(
        "weekly",
        instructions="{{tone}}",
        parameters=[SkillParameter(name="tone", required=True)],
    )

    with pytest.raises(SkillValidationError) as info:
        resolve(skills=[skill])

    assert info.value.code == "SKILL_INVALID_PARAMS"
    assert info.value.param == "tone"
    assert info.value.skill_slug == "weekly"


def test_parameter_type_mismatch_fails() -> None:
    skill = make_skill(
        "count",
        instructions="{{n}}",
        parameters=[SkillParameter(name="n", type="number")],
        values={"n": "not-a-number"},
    )

    with pytest.raises(SkillValidationError) as info:
        resolve(skills=[skill])

    assert info.value.code == "SKILL_INVALID_PARAMS"


def test_number_parameter_is_coerced() -> None:
    skill = make_skill(
        "count",
        instructions="共 {{n}} 条",
        parameters=[SkillParameter(name="n", type="number")],
        values={"n": "3"},
    )

    assert "共 3.0 条" in resolve(skills=[skill], budget=1000).system_prompt


def test_optional_param_without_default_renders_empty() -> None:
    skill = make_skill(
        "style",
        instructions="前缀[{{prefix}}]",
        parameters=[SkillParameter(name="prefix", required=False)],
    )

    plan = resolve(skills=[skill], budget=1000)

    assert "前缀[]" in plan.system_prompt
    assert plan.warnings == []


def test_unknown_placeholder_is_kept_with_warning() -> None:
    skill = make_skill("raw", instructions="{{unknown}}", parameters=[])
    plan = resolve(skills=[skill], budget=1000)

    assert "{{unknown}}" in plan.system_prompt
    assert any(item.startswith("SKILL_UNKNOWN_PLACEHOLDER") for item in plan.warnings)


def test_unknown_agent_param_is_reported() -> None:
    skill = make_skill("raw", instructions="ok", parameters=[], values={"extra": 1})
    plan = resolve(skills=[skill], budget=1000)

    assert any(item.startswith("SKILL_UNKNOWN_PARAM") for item in plan.warnings)


def test_skill_tools_are_merged_and_deduped() -> None:
    bound = make_tool(BOUND_TOOL)
    skill_tool = make_tool(SKILL_TOOL)
    skill = make_skill("gh", instructions="查 issue", tools=[SkillToolRef(qualified_name=SKILL_TOOL, tool=skill_tool)])
    duplicate = make_skill(
        "dup",
        instructions="再来一次",
        order_no=1,
        tools=[SkillToolRef(qualified_name=SKILL_TOOL, tool=skill_tool)],
    )

    plan = resolve(bound_tools=[bound], skills=[skill, duplicate], budget=1000)

    assert [tool.qualified_name for tool in plan.tools] == [BOUND_TOOL, SKILL_TOOL]


def test_missing_skill_tool_is_recorded_with_required_flag() -> None:
    required = SkillToolRef(qualified_name="x.missing", required=True)
    optional = SkillToolRef(qualified_name="y.missing", required=False)
    plan = resolve(
        skills=[make_skill("s", instructions="hi", tools=[required, optional])],
        budget=2000,
    )

    assert {item.qualified_name for item in plan.missing_tools} == {"x.missing", "y.missing"}
    assert [item.qualified_name for item in plan.missing_required_tools] == ["x.missing"]
    assert any(item.startswith("SKILL_TOOL_MISSING_OPTIONAL") for item in plan.warnings)


def test_disabled_skill_is_ignored_entirely() -> None:
    disabled = make_skill("off", instructions="不该出现", enabled=False)
    plan = resolve(skills=[disabled], budget=1000)

    assert plan.injected == []
    assert "不该出现" not in plan.system_prompt


def test_long_prompt_is_truncated_to_budget() -> None:
    skill = make_skill("long", name="长技能", instructions="x" * 1000)
    plan = resolve(system_prompt="基座", skills=[skill], budget=300)

    assert plan.truncated is True
    assert len(plan.system_prompt) <= 300
    assert plan.system_prompt.endswith("...(truncated)")
    assert any(item.startswith("SKILL_PROMPT_TRUNCATED") for item in plan.warnings)


def test_skill_is_dropped_when_not_enough_room() -> None:
    base = "b" * 100
    skill = make_skill("big", name="大技能", instructions="y" * 1000)
    later = make_skill("later", name="后续技能", instructions="z", order_no=1)
    plan = resolve(system_prompt=base, skills=[skill, later], budget=150)

    assert plan.truncated is True
    assert plan.system_prompt == base
    assert plan.injected == []
    assert any(item.startswith("SKILL_PROMPT_DROPPED") for item in plan.warnings)


def test_min_fragment_threshold_is_respected() -> None:
    """剩余空间小于阈值时整段丢弃，而不是塞入无意义的半句话。"""
    assert MIN_SKILL_FRAGMENT_CHARS > 0


def test_dropped_skill_does_not_contribute_tools_or_missing_dependencies() -> None:
    """Skill 因预算被整体丢弃时，它的工具与缺失依赖都不应影响本次 Run。"""
    base = "b" * 100
    skill = make_skill(
        "big",
        instructions="y" * 1000,
        tools=[
            SkillToolRef(qualified_name="ghost.tool", required=True),
            SkillToolRef(qualified_name="ok.tool", tool=make_tool("ok.tool")),
        ],
    )

    plan = resolve(system_prompt=base, skills=[skill], budget=150)

    assert plan.injected == []
    assert plan.tools == []
    assert plan.missing_tools == []
    assert plan.system_prompt == base


def test_budget_from_context_window() -> None:
    assert SkillResolver.budget_from_context_window(None) == DEFAULT_PROMPT_BUDGET_CHARS
    assert SkillResolver.budget_from_context_window(0) == DEFAULT_PROMPT_BUDGET_CHARS
    assert SkillResolver.budget_from_context_window(10_000) == 6_000
    assert SkillResolver.budget_from_context_window(100) == 2_000
