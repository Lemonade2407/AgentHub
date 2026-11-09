"""V2 Agent 发布快照的序列化与脱敏校验。归属：A（Runtime）+ D（发布接口）。

发布采用**不可变快照**而不是引用：安装者拿到的是自己的一份副本，原作者改动或删除
都不会影响已安装的 Agent。因此本模块只做两件事：

1. `build_agent_snapshot`：把 Agent + Skill + 工具依赖序列化为白名单结构；
2. `parse_agent_snapshot`：校验安装侧收到的快照结构，并拒绝任何敏感字段。

白名单之外的一切字段（`api_key`、MCP `headers`、`owner_id`、内部主键等）都不得出现。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.skills import SkillDefinition
from app.schemas.agent import AgentRead

SNAPSHOT_SCHEMA_VERSION = 1

# 快照中出现即视为泄露的字段名（大小写不敏感）
FORBIDDEN_SNAPSHOT_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "api_key_cipher",
        "api_key_hint",
        "apikey",
        "authorization",
        "headers",
        "mcp_headers",
        "owner_id",
        "model_api_id",
        "password",
        "password_hash",
        "secret",
        "token",
    }
)


class SnapshotError(ValueError):
    """快照不合法或包含敏感字段。"""

    def __init__(self, code: str, message: str, *, paths: Sequence[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.paths = list(paths or [])


class SnapshotAgent(BaseModel):
    """Agent 定义中允许被分享的部分。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)
    system_prompt: str = ""
    max_steps: int = Field(default=8, ge=1, le=20)
    required_capabilities: list[str] = Field(default_factory=list)


class SuggestedModel(BaseModel):
    """安装时的模型建议：只给 provider + 模型名，不含任何凭据。"""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=32)
    model_key: str = Field(min_length=1, max_length=128)


class SnapshotSkill(BaseModel):
    """Skill 引用：按 `slug + version` 匹配，安装时复制或提示安装。"""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=80)
    version: str = Field(default="1.0.0", max_length=16)
    params: dict[str, Any] = Field(default_factory=dict)


class SnapshotTool(BaseModel):
    """工具依赖：只保留定位信息，绝不包含 MCP `headers`。"""

    model_config = ConfigDict(extra="forbid")

    server_name: str = Field(min_length=1, max_length=64)
    remote_name: str = Field(min_length=1, max_length=128)
    transport: str | None = None
    endpoint: str | None = None
    required: bool = True


class AgentSnapshot(BaseModel):
    """发布快照的完整结构（`schema_version` 决定兼容策略）。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = SNAPSHOT_SCHEMA_VERSION
    agent: SnapshotAgent
    suggested_model: SuggestedModel
    skills: list[SnapshotSkill] = Field(default_factory=list)
    tools: list[SnapshotTool] = Field(default_factory=list)


def build_agent_snapshot(
    *,
    agent: AgentRead,
    skills: Sequence[SkillDefinition] = (),
    tool_dependencies: Sequence[SnapshotTool] | None = None,
    suggested_model: SuggestedModel | None = None,
) -> AgentSnapshot:
    """构造发布快照。

    `tool_dependencies` 由 D/B 从 Tool Registry + MCP Server 表补齐（可带 transport/endpoint）；
    不传时只能从 Skill 已解析的 Tool 上取 `server_name + remote_name`，作为最小依赖集。
    """
    enabled_skills = sorted(
        (skill for skill in skills if skill.enabled),
        key=lambda skill: (skill.order_no, skill.slug),
    )

    deps = list(tool_dependencies) if tool_dependencies is not None else _derive_tool_deps(enabled_skills)

    snapshot = AgentSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        agent=SnapshotAgent(
            name=agent.name,
            description=agent.description,
            system_prompt=agent.system_prompt,
            max_steps=agent.max_steps,
            required_capabilities=["tool_call"] if deps else [],
        ),
        suggested_model=suggested_model or _suggested_model_from(agent.model),
        skills=[
            SnapshotSkill(slug=skill.slug, version=skill.version, params=dict(skill.values))
            for skill in enabled_skills
        ],
        tools=deps,
    )
    # 白名单模型理论上不可能带敏感字段；这里再校验一次，防止未来加字段时回归
    assert_snapshot_sanitized(snapshot.model_dump(mode="json"))
    return snapshot


def dump_snapshot(snapshot: AgentSnapshot) -> dict[str, Any]:
    """序列化为可直接写入 `agent_publication.snapshot`（JSONB）的 dict。"""
    data = snapshot.model_dump(mode="json")
    assert_snapshot_sanitized(data)
    return data


def parse_agent_snapshot(raw: Mapping[str, Any]) -> AgentSnapshot:
    """安装侧解析快照：先拒绝敏感字段，再按严格模型校验。"""
    assert_snapshot_sanitized(raw)
    try:
        snapshot = AgentSnapshot.model_validate(raw)
    except ValidationError as exc:
        raise SnapshotError("SNAPSHOT_INVALID", f"快照结构不合法：{exc}"[:512]) from None
    if snapshot.schema_version != SNAPSHOT_SCHEMA_VERSION:
        raise SnapshotError(
            "SNAPSHOT_VERSION_UNSUPPORTED",
            f"不支持的快照版本：{snapshot.schema_version}",
        )
    return snapshot


def find_forbidden_keys(value: Any, *, path: str = "$") -> list[str]:
    """递归查找敏感字段，返回形如 `$.agent.api_key` 的路径列表。"""
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if key_text.lower() in FORBIDDEN_SNAPSHOT_KEYS:
                paths.append(child_path)
            paths.extend(find_forbidden_keys(child, path=child_path))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            paths.extend(find_forbidden_keys(child, path=f"{path}[{index}]"))
    return paths


def assert_snapshot_sanitized(raw: Mapping[str, Any]) -> None:
    paths = find_forbidden_keys(raw)
    if paths:
        raise SnapshotError(
            "SNAPSHOT_CONTAINS_SECRET",
            "快照包含敏感字段，禁止发布：" + ", ".join(paths),
            paths=paths,
        )


def _derive_tool_deps(skills: Sequence[SkillDefinition]) -> list[SnapshotTool]:
    deps: list[SnapshotTool] = []
    seen: set[tuple[str, str]] = set()
    for skill in skills:
        for ref in skill.tools:
            if ref.tool is not None:
                server_name, remote_name = ref.tool.server_name, ref.tool.remote_name
            else:
                server_name, remote_name = _split_qualified_name(ref.qualified_name)
            key = (server_name, remote_name)
            if key in seen:
                continue
            seen.add(key)
            deps.append(
                SnapshotTool(server_name=server_name, remote_name=remote_name, required=ref.required)
            )
    return deps


def _split_qualified_name(qualified_name: str) -> tuple[str, str]:
    server_name, _, remote_name = qualified_name.partition(".")
    if not server_name:
        return qualified_name, qualified_name
    return server_name, remote_name or qualified_name


def _suggested_model_from(model: str) -> SuggestedModel:
    provider, _, name = model.partition("/")
    if not provider or not name:
        return SuggestedModel(provider="custom", model_key=model)
    return SuggestedModel(provider=provider, model_key=name)
