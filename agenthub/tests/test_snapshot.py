"""发布快照序列化与脱敏校验单元测试（V2：Agent Center）。"""

from __future__ import annotations

import pytest

from app.agent.skills import SkillToolRef
from app.agent.snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    AgentSnapshot,
    SnapshotError,
    SnapshotTool,
    SuggestedModel,
    build_agent_snapshot,
    dump_snapshot,
    find_forbidden_keys,
    parse_agent_snapshot,
)
from tests.fakes import make_agent, make_skill, make_tool


def test_builds_whitelisted_snapshot() -> None:
    skill = make_skill(
        "weekly",
        name="周报生成",
        values={"tone": "轻松"},
        tools=[SkillToolRef(qualified_name="github.list_issues", tool=make_tool("github.list_issues"))],
    )
    snapshot = build_agent_snapshot(agent=make_agent(), skills=[skill])

    assert isinstance(snapshot, AgentSnapshot)
    assert snapshot.schema_version == SNAPSHOT_SCHEMA_VERSION
    assert snapshot.agent.name == "Research Agent"
    assert snapshot.agent.required_capabilities == ["tool_call"]
    assert snapshot.suggested_model.provider == "deepseek"
    assert snapshot.suggested_model.model_key == "deepseek-chat"
    assert snapshot.skills[0].slug == "weekly"
    assert snapshot.skills[0].params == {"tone": "轻松"}
    assert snapshot.tools[0].server_name == "github"
    assert snapshot.tools[0].remote_name == "list_issues"


def test_snapshot_never_contains_secrets_or_internal_ids() -> None:
    skill = make_skill(
        "weekly",
        tools=[SkillToolRef(qualified_name="github.list_issues", tool=make_tool("github.list_issues"))],
    )
    data = dump_snapshot(build_agent_snapshot(agent=make_agent(), skills=[skill]))

    assert find_forbidden_keys(data) == []
    assert "api_key" not in str(data)
    assert "headers" not in str(data)
    assert "owner_id" not in str(data)
    assert "model_api_id" not in str(data)
    assert "tool_ids" not in str(data)


def test_explicit_tool_dependencies_are_used_as_is() -> None:
    deps = [
        SnapshotTool(
            server_name="git-tools",
            remote_name="list_commits",
            transport="streamable_http",
            endpoint="https://example.com/mcp",
        )
    ]
    snapshot = build_agent_snapshot(agent=make_agent(), tool_dependencies=deps)

    assert snapshot.tools == deps
    assert snapshot.agent.required_capabilities == ["tool_call"]


def test_no_tools_means_no_tool_call_capability() -> None:
    snapshot = build_agent_snapshot(agent=make_agent(system_prompt=""))
    assert snapshot.agent.required_capabilities == []


def test_custom_suggested_model_wins() -> None:
    snapshot = build_agent_snapshot(
        agent=make_agent(),
        suggested_model=SuggestedModel(provider="qwen", model_key="qwen-plus"),
    )
    assert snapshot.suggested_model.model_key == "qwen-plus"


def test_legacy_model_without_provider_prefix() -> None:
    snapshot = build_agent_snapshot(agent=make_agent(model="local-model"))
    assert snapshot.suggested_model.provider == "custom"
    assert snapshot.suggested_model.model_key == "local-model"


def test_snapshot_round_trip() -> None:
    data = dump_snapshot(build_agent_snapshot(agent=make_agent(), skills=[make_skill("weekly")]))
    parsed = parse_agent_snapshot(data)

    assert parsed.agent.name == "Research Agent"
    assert parsed.skills[0].slug == "weekly"


def test_parse_rejects_unknown_fields() -> None:
    data = dump_snapshot(build_agent_snapshot(agent=make_agent()))
    data["agent"]["owner_id"] = 42  # type: ignore[index]

    with pytest.raises(SnapshotError) as info:
        parse_agent_snapshot(data)

    # 先被脱敏扫描拦截，而不是被 pydantic 的 extra=forbid 拦截
    assert info.value.code == "SNAPSHOT_CONTAINS_SECRET"
    assert "$.agent.owner_id" in info.value.paths


def test_parse_rejects_unknown_top_level_field() -> None:
    data = dump_snapshot(build_agent_snapshot(agent=make_agent()))
    data["unexpected"] = True

    with pytest.raises(SnapshotError) as info:
        parse_agent_snapshot(data)

    assert info.value.code == "SNAPSHOT_INVALID"


def test_parse_rejects_unsupported_version() -> None:
    data = dump_snapshot(build_agent_snapshot(agent=make_agent()))
    data["schema_version"] = 99

    with pytest.raises(SnapshotError) as info:
        parse_agent_snapshot(data)

    assert info.value.code == "SNAPSHOT_VERSION_UNSUPPORTED"


def test_forbidden_keys_are_found_recursively() -> None:
    raw = {
        "agent": {"name": "x"},
        "skills": [{"slug": "s", "params": {"api_key": "sk-1"}}],
        "tools": [{"server_name": "s", "remote_name": "r", "headers": {"Authorization": "x"}}],
    }
    paths = find_forbidden_keys(raw)

    assert "$.skills[0].params.api_key" in paths
    assert "$.tools[0].headers" in paths


def test_build_rejects_forbidden_tool_dependency_field() -> None:
    """Pydantic 的 extra=forbid 会成为第二道防线。"""
    with pytest.raises(Exception):
        SnapshotTool(server_name="s", remote_name="r", headers={"a": "b"})  # type: ignore[call-arg]
