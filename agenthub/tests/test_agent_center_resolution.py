"""Agent Center 依赖解析纯函数单测（WP-3.3）。"""

from __future__ import annotations

from app.agent.snapshot import AgentSnapshot, SnapshotAgent, SnapshotSkill, SnapshotTool
from app.models.skill import Skill
from app.services.agent_center_service import ToolLookup, resolve_dependencies
from tests.fakes import make_tool


def make_snapshot(
    *,
    skills: list[SnapshotSkill] | None = None,
    tools: list[SnapshotTool] | None = None,
) -> AgentSnapshot:
    return AgentSnapshot(
        agent=SnapshotAgent(
            name="周报助手",
            description="把本周工作整理成周报",
            system_prompt="你是助理。",
            max_steps=8,
        ),
        suggested_model={"provider": "deepseek", "model_key": "deepseek-chat"},
        skills=skills or [],
        tools=tools or [],
    )


def make_skill(
    *,
    skill_id: int = 1,
    slug: str = "weekly",
    version: str = "1.0.0",
    schema: dict | None = None,
) -> Skill:
    return Skill(
        id=skill_id,
        owner_id=1,
        name=slug,
        slug=slug,
        version=version,
        input_schema=schema or {},
        instructions="写周报",
        summary="",
        category="general",
        visibility="public",
        status="published",
    )


def test_all_dependencies_resolve() -> None:
    tool = make_tool("github.list_issues", id=10, server_name="github", remote_name="list_issues")
    plan = resolve_dependencies(
        make_snapshot(
            skills=[SnapshotSkill(slug="weekly", version="1.0.0")],
            tools=[SnapshotTool(server_name="github", remote_name="list_issues")],
        ),
        local_skills={"weekly": make_skill()},
        public_skills={},
        tool_results={("github", "list_issues"): ToolLookup(tool)},
    )

    assert plan.blocking_missing is False
    assert [item.skill.slug for item in plan.skills] == ["weekly"]
    assert plan.skills[0].source == "local"
    assert [item.tool_id for item in plan.tools] == [10]
    assert plan.missing_skills == []
    assert plan.missing_tools == []


def test_public_skill_is_used_when_local_missing() -> None:
    plan = resolve_dependencies(
        make_snapshot(skills=[SnapshotSkill(slug="weekly", version="1.0.0")]),
        local_skills={},
        public_skills={("weekly", "1.0.0"): make_skill(skill_id=7)},
        tool_results={},
    )

    assert plan.blocking_missing is False
    assert plan.skills[0].skill.id == 7
    assert plan.skills[0].source == "public"


def test_missing_skill_blocks_install() -> None:
    plan = resolve_dependencies(
        make_snapshot(skills=[SnapshotSkill(slug="weekly", version="1.0.0")]),
        local_skills={},
        public_skills={},
        tool_results={},
    )

    assert plan.blocking_missing is True
    assert len(plan.missing_skills) == 1
    assert plan.missing_skills[0].slug == "weekly"
    assert plan.missing_skills[0].required is True


def test_version_mismatch_public_skill_is_missing() -> None:
    plan = resolve_dependencies(
        make_snapshot(skills=[SnapshotSkill(slug="weekly", version="2.0.0")]),
        local_skills={},
        public_skills={("weekly", "1.0.0"): make_skill()},
        tool_results={},
    )

    assert plan.blocking_missing is True
    assert plan.missing_skills[0].version == "2.0.0"


def test_required_and_optional_missing_tools() -> None:
    plan = resolve_dependencies(
        make_snapshot(
            tools=[
                SnapshotTool(server_name="gh", remote_name="list", required=True),
                SnapshotTool(server_name="web", remote_name="search", required=False),
            ]
        ),
        local_skills={},
        public_skills={},
        tool_results={
            ("gh", "list"): ToolLookup(None, "MCP Server 未注册：gh"),
            ("web", "search"): ToolLookup(None, "Tool 已禁用：web.search"),
        },
    )

    assert plan.blocking_missing is True
    assert {item.server_name for item in plan.missing_tools} == {"gh", "web"}
    assert plan.missing_tools[0].reason.startswith("MCP Server 未注册")


def test_optional_missing_tool_does_not_block() -> None:
    plan = resolve_dependencies(
        make_snapshot(
            tools=[SnapshotTool(server_name="web", remote_name="search", required=False)]
        ),
        local_skills={},
        public_skills={},
        tool_results={("web", "search"): ToolLookup(None, "Tool 未注册")},
    )

    assert plan.blocking_missing is False
    assert len(plan.missing_tools) == 1


def test_invalid_params_only_adds_warning() -> None:
    skill = make_skill(
        schema={
            "type": "object",
            "properties": {"tone": {"type": "string"}},
            "required": ["tone"],
        }
    )
    plan = resolve_dependencies(
        make_snapshot(skills=[SnapshotSkill(slug="weekly", version="1.0.0", params={})]),
        local_skills={"weekly": skill},
        public_skills={},
        tool_results={},
    )

    assert plan.blocking_missing is False
    assert len(plan.skills) == 1
    assert any(item.startswith("SKILL_PARAMS_INVALID:weekly") for item in plan.warnings)


def test_duplicate_tool_references_are_deduped() -> None:
    tool = make_tool("github.list_issues", id=10, server_name="github", remote_name="list_issues")
    plan = resolve_dependencies(
        make_snapshot(
            tools=[
                SnapshotTool(server_name="github", remote_name="list_issues"),
                SnapshotTool(server_name="github", remote_name="list_issues"),
            ]
        ),
        local_skills={},
        public_skills={},
        tool_results={("github", "list_issues"): ToolLookup(tool)},
    )

    assert len(plan.tools) == 1
    assert plan.missing_tools == []
