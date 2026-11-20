"""Agent Center 依赖预检与安装算法。归属：B（依赖解析）+ D（发布/安装落库）。

对应修改意见 §5.6 与 WP-3.3：

1. 读取 `publication.snapshot` 并校验 schema_version；
2. Skill 依赖：本地同名（owner=me）→ 公开同名且版本匹配 → 缺失；
3. Tool 依赖：按 `(server_name, remote_name)` 在本地 Tool Registry 查找 → 缺失；
4. 存在 required 缺失且未 `confirm_missing` → 返回 409 + 缺失清单；
5. 事务内创建 Agent + `agent_skill` + `agent_tool`，名称冲突追加“(副本)”；
6. 写 `publication_install` 并原子递增 `install_count`；
7. 返回新 `agent_id` 与“安装后仍需处理的事项”。

模型不强制匹配：安装后沿用快照建议的 `provider/model`，并提示安装者配置自己的 Model API。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.skills import SkillValidationError
from app.agent.snapshot import (
    AgentSnapshot,
    SnapshotError,
    SnapshotSkill,
    SnapshotTool,
    parse_agent_snapshot,
)
from app.core.enums import PublicationStatus, RiskLevel, SkillStatus, SkillVisibility
from app.core.errors import AppError
from app.db.models import Agent as AgentRow
from app.db.models import AgentTool as AgentToolRow
from app.mcp.schemas import ToolDefinition
from app.models.mcp import McpServer, McpTool
from app.models.model_api import ModelApi
from app.models.publication import AgentPublication, PublicationInstall
from app.models.skill import AgentSkill, Skill
from app.schemas.agent_center import (
    InstallRead,
    MissingSkillRead,
    MissingToolRead,
    PrecheckRead,
    SuggestedModelRead,
)
from app.services.skill_service import parameters_from_schema, validate_params


@dataclass(frozen=True)
class ToolLookup:
    """本地 Tool Registry 的查询结果；`definition=None` 时 `reason` 说明原因。"""

    definition: ToolDefinition | None
    reason: str = ""


@dataclass(frozen=True)
class ResolvedSkillDependency:
    snapshot: SnapshotSkill
    skill: Skill
    source: Literal["local", "public"]


@dataclass(frozen=True)
class ResolvedToolDependency:
    snapshot: SnapshotTool
    tool: ToolDefinition
    tool_id: int


@dataclass
class DependencyPlan:
    skills: list[ResolvedSkillDependency] = field(default_factory=list)
    tools: list[ResolvedToolDependency] = field(default_factory=list)
    missing_skills: list[MissingSkillRead] = field(default_factory=list)
    missing_tools: list[MissingToolRead] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def blocking_missing(self) -> bool:
        return any(item.required for item in self.missing_skills) or any(
            item.required for item in self.missing_tools
        )


def resolve_dependencies(
    snapshot: AgentSnapshot,
    *,
    local_skills: Mapping[str, Skill],
    public_skills: Mapping[tuple[str, str], Skill],
    tool_results: Mapping[tuple[str, str], ToolLookup],
) -> DependencyPlan:
    """纯函数：把快照依赖解析为“可安装项 + 缺失项”，不做数据库访问。"""
    plan = DependencyPlan()
    seen_skill_ids: set[int] = set()
    seen_tool_keys: set[tuple[str, str]] = set()

    for ref in snapshot.skills:
        local = local_skills.get(ref.slug)
        public = public_skills.get((ref.slug, ref.version))
        chosen = local or public
        if chosen is None:
            plan.missing_skills.append(
                MissingSkillRead(
                    slug=ref.slug,
                    version=ref.version,
                    params=dict(ref.params),
                    required=True,
                    reason="本地与公开广场均未找到匹配 Skill",
                )
            )
            continue
        if chosen.id in seen_skill_ids:
            continue
        seen_skill_ids.add(chosen.id)

        try:
            validate_params(parameters_from_schema(chosen.input_schema), ref.params)
        except SkillValidationError as exc:
            # 参数契约不匹配不阻断安装：装完后运行时仍会给出明确错误
            plan.warnings.append(f"SKILL_PARAMS_INVALID:{ref.slug}:{exc.message}")

        plan.skills.append(
            ResolvedSkillDependency(
                snapshot=ref,
                skill=chosen,
                source="local" if local is not None else "public",
            )
        )

    for dep in snapshot.tools:
        key = (dep.server_name, dep.remote_name)
        if key in seen_tool_keys:
            continue
        seen_tool_keys.add(key)

        lookup = tool_results.get(key)
        if lookup is None or lookup.definition is None:
            plan.missing_tools.append(
                MissingToolRead(
                    server_name=dep.server_name,
                    remote_name=dep.remote_name,
                    required=dep.required,
                    reason=lookup.reason if lookup else "Tool Registry 未返回结果",
                )
            )
            continue
        plan.tools.append(
            ResolvedToolDependency(
                snapshot=dep,
                tool=lookup.definition,
                tool_id=lookup.definition.id,
            )
        )

    return plan


class AgentCenterService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # 预检
    # ------------------------------------------------------------------

    async def precheck(self, *, publication_id: int, installer_id: int) -> PrecheckRead:
        publication = await self._get_publication(publication_id)
        snapshot = _parse_snapshot(publication)
        existing = await self._existing_install(publication_id, installer_id)
        plan = await self._resolve(installer_id, snapshot)
        warnings = list(plan.warnings)

        default_api = await self._default_model_api(installer_id)
        if default_api is None:
            warnings.append("MODEL_API_NOT_CONFIGURED: 安装后请先配置模型 API")

        suggested = snapshot.suggested_model
        return PrecheckRead(
            publication_id=publication.id,
            title=publication.title,
            can_install=not plan.blocking_missing and existing is None,
            already_installed=existing is not None,
            installed_agent_id=existing.installed_agent_id if existing else None,
            resolved_skills=len(plan.skills),
            resolved_tools=len(plan.tools),
            missing_skills=plan.missing_skills,
            missing_tools=plan.missing_tools,
            warnings=warnings,
            suggested_model=SuggestedModelRead(
                provider=suggested.provider,
                model_key=suggested.model_key,
            )
            if suggested is not None
            else None,
        )

    # ------------------------------------------------------------------
    # 安装
    # ------------------------------------------------------------------

    async def install(
        self,
        *,
        publication_id: int,
        installer_id: int,
        confirm_missing: bool,
    ) -> InstallRead:
        publication = await self._get_publication(publication_id)
        snapshot = _parse_snapshot(publication)

        existing = await self._existing_install(publication_id, installer_id)
        if existing is not None:
            raise AppError(
                "ALREADY_INSTALLED",
                "已安装过该 Agent，请直接编辑已有副本",
                http_status=409,
                detail={"agent_id": existing.installed_agent_id},
            )

        plan = await self._resolve(installer_id, snapshot)
        if plan.blocking_missing and not confirm_missing:
            raise AppError(
                "INSTALL_DEPENDENCY_MISSING",
                "安装依赖缺失，请补齐后重试或确认跳过",
                http_status=409,
                detail={
                    "missing_skills": [item.model_dump() for item in plan.missing_skills],
                    "missing_tools": [item.model_dump() for item in plan.missing_tools],
                },
            )

        agent_name = await self._unique_agent_name(snapshot.agent.name)
        # 模型统一在对话窗口选择：安装副本不再绑定默认 / 推荐模型
        agent = AgentRow(
            name=agent_name,
            description=snapshot.agent.description,
            model="",
            system_prompt=snapshot.agent.system_prompt,
            max_steps=snapshot.agent.max_steps,
            enabled=True,
        )
        self._session.add(agent)
        await self._session.flush()

        # V1 自动建表环境的 agent 表没有 owner_id / model_api_id 列：
        # 仅在列存在时写入，保证“安装者拥有副本”的语义（§5.6）且不破坏 V1。
        await self._assign_agent_scope(
            agent_id=agent.id,
            installer_id=installer_id,
            model_api_id=None,
            model_key=None,
        )

        for order_no, item in enumerate(plan.skills):
            self._session.add(
                AgentSkill(
                    agent_id=agent.id,
                    skill_id=item.skill.id,
                    order_no=order_no,
                    enabled=True,
                    params=dict(item.snapshot.params),
                )
            )
        for item in plan.tools:
            self._session.add(AgentToolRow(agent_id=agent.id, tool_id=item.tool_id))

        self._session.add(
            PublicationInstall(
                publication_id=publication.id,
                installer_id=installer_id,
                installed_agent_id=agent.id,
            )
        )
        try:
            # 执行 UPDATE 会触发 autoflush：把安装记录的唯一约束冲突也纳入回滚范围
            await self._session.execute(
                update(AgentPublication)
                .where(AgentPublication.id == publication.id)
                .values(install_count=AgentPublication.install_count + 1)
            )
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise AppError(
                "ALREADY_INSTALLED",
                "已安装过该 Agent",
                http_status=409,
            ) from exc

        warnings = list(plan.warnings)
        if default_api is None:
            warnings.append("MODEL_API_NOT_CONFIGURED: 安装后请先配置模型 API")

        return InstallRead(
            publication_id=publication.id,
            agent_id=agent.id,
            installed_skill_ids=[item.skill.id for item in plan.skills],
            installed_tool_ids=[item.tool_id for item in plan.tools],
            missing_skills=plan.missing_skills,
            missing_tools=plan.missing_tools,
            warnings=warnings,
            next_steps=_next_steps(plan, model_ready=not any(
                item.startswith("MODEL_API_NOT_CONFIGURED") for item in warnings
            )),
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _get_publication(self, publication_id: int) -> AgentPublication:
        publication = (
            await self._session.execute(
                select(AgentPublication).where(AgentPublication.id == publication_id)
            )
        ).scalar_one_or_none()
        if publication is None:
            raise AppError(
                "PUBLICATION_NOT_FOUND",
                f"Publication 不存在：{publication_id}",
                http_status=404,
            )
        if publication.status != PublicationStatus.PUBLISHED.value:
            raise AppError(
                "PUBLICATION_OFFLINE",
                "该 Agent 已下架或尚未发布",
                http_status=409,
            )
        return publication

    async def _existing_install(
        self, publication_id: int, installer_id: int
    ) -> PublicationInstall | None:
        return (
            await self._session.execute(
                select(PublicationInstall).where(
                    PublicationInstall.publication_id == publication_id,
                    PublicationInstall.installer_id == installer_id,
                )
            )
        ).scalar_one_or_none()

    async def _resolve(self, installer_id: int, snapshot: AgentSnapshot) -> DependencyPlan:
        slugs = sorted({item.slug for item in snapshot.skills})
        local_skills: dict[str, Skill] = {}
        if slugs:
            rows = (
                (
                    await self._session.execute(
                        select(Skill)
                        .where(Skill.owner_id == installer_id, Skill.slug.in_(slugs))
                        .order_by(Skill.updated_at.desc(), Skill.id.desc())
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                local_skills.setdefault(row.slug, row)

        public_skills: dict[tuple[str, str], Skill] = {}
        for ref in snapshot.skills:
            if ref.slug in local_skills:
                continue
            row = (
                await self._session.execute(
                    select(Skill)
                    .where(
                        Skill.slug == ref.slug,
                        Skill.version == ref.version,
                        Skill.visibility == SkillVisibility.PUBLIC.value,
                        Skill.status == SkillStatus.PUBLISHED.value,
                    )
                    .order_by(Skill.updated_at.desc(), Skill.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is not None:
                public_skills[(ref.slug, ref.version)] = row

        tool_results: dict[tuple[str, str], ToolLookup] = {}
        for dep in snapshot.tools:
            key = (dep.server_name, dep.remote_name)
            if key in tool_results:
                continue
            tool_results[key] = await self._lookup_tool(dep)

        return resolve_dependencies(
            snapshot,
            local_skills=local_skills,
            public_skills=public_skills,
            tool_results=tool_results,
        )

    async def _lookup_tool(self, dep: SnapshotTool) -> ToolLookup:
        server = (
            await self._session.execute(
                select(McpServer).where(McpServer.name == dep.server_name)
            )
        ).scalar_one_or_none()
        if server is None:
            return ToolLookup(None, f"MCP Server 未注册：{dep.server_name}")

        tool = (
            await self._session.execute(
                select(McpTool).where(
                    McpTool.server_id == server.id,
                    McpTool.remote_name == dep.remote_name,
                )
            )
        ).scalar_one_or_none()
        if tool is None:
            return ToolLookup(
                None,
                f"Tool 未注册：{dep.server_name}.{dep.remote_name}",
            )
        if not tool.enabled:
            return ToolLookup(
                None,
                f"Tool 已禁用：{dep.server_name}.{dep.remote_name}",
            )
        return ToolLookup(_to_definition(tool, server.name))

    async def _default_model_api(self, installer_id: int) -> ModelApi | None:
        return (
            await self._session.execute(
                select(ModelApi).where(
                    ModelApi.owner_id == installer_id,
                    ModelApi.is_default.is_(True),
                    ModelApi.enabled.is_(True),
                )
            )
        ).scalar_one_or_none()

    async def _assign_agent_scope(
        self,
        *,
        agent_id: int,
        installer_id: int,
        model_api_id: int | None,
        model_key: str | None,
    ) -> None:
        """把安装者写回 `agent` 的 V2 字段；列不存在时（纯 V1 自动建表）跳过。"""
        columns = set(
            (
                await self._session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'agent' AND table_schema = current_schema()"
                    )
                )
            )
            .scalars()
            .all()
        )
        assignments = ["owner_id = :owner_id"]
        params: dict[str, object] = {"agent_id": agent_id, "owner_id": installer_id}
        if model_api_id is not None and "model_api_id" in columns:
            assignments.append("model_api_id = :model_api_id")
            params["model_api_id"] = model_api_id
        if model_key is not None and "model_key" in columns:
            assignments.append("model_key = :model_key")
            params["model_key"] = model_key
        if "owner_id" not in columns:
            return
        await self._session.execute(
            text(f"UPDATE agent SET {', '.join(assignments)} WHERE id = :agent_id"),
            params,
        )

    async def _unique_agent_name(self, base_name: str) -> str:
        base = (base_name or "Agent").strip()[:64] or "Agent"
        candidate = base
        suffix_no = 2
        while (
            await self._session.execute(
                select(AgentRow.id).where(
                    AgentRow.name == candidate,
                    AgentRow.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none() is not None:
            suffix = "(副本)" if suffix_no == 2 else f"(副本{suffix_no - 1})"
            candidate = f"{base[: 64 - len(suffix)]}{suffix}"
            suffix_no += 1
        return candidate


def _parse_snapshot(publication: AgentPublication) -> AgentSnapshot:
    try:
        return parse_agent_snapshot(publication.snapshot or {})
    except SnapshotError as exc:
        raise AppError(exc.code, exc.message, http_status=400) from exc


def _to_definition(tool: McpTool, server_name: str) -> ToolDefinition:
    return ToolDefinition(
        id=tool.id,
        server_id=tool.server_id,
        server_name=server_name,
        remote_name=tool.remote_name,
        qualified_name=tool.qualified_name,
        description=tool.description,
        input_schema=tool.input_schema or {},
        risk_level=RiskLevel(tool.risk_level),
        enabled=tool.enabled,
        updated_at=tool.updated_at,
    )


def _next_steps(plan: DependencyPlan, *, model_ready: bool) -> list[str]:
    steps: list[str] = []
    if not model_ready:
        steps.append("先在「模型 API」中配置可用模型，并在对话窗口选择")
    for item in plan.missing_skills:
        steps.append(f"安装缺失 Skill：{item.slug} v{item.version}")
    for item in plan.missing_tools:
        steps.append(f"注册 MCP Server 并 Discovery：{item.server_name}（缺少 {item.remote_name}）")
    if not steps:
        steps.append("依赖已齐备，可直接打开对话窗口并选择模型运行")
    return steps
