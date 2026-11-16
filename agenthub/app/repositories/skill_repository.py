"""Skill 仓储：Skill CRUD、广场、安装、导出与 Agent 挂载解析。

归属：D（Platform Backend）；`resolve_for_agent` 为 A（Runtime）提供只读解析结果，
工具可用性判断（enabled / required）属于 B（工具侧）契约。

设计要点：
- 所有读写都以 `owner_id` 收敛；跨用户访问一律返回 `SKILL_NOT_FOUND`（§8 权限）；
- 删除被 Agent 挂载的 Skill 返回 `SKILL_IN_USE`，由外键 `ON DELETE RESTRICT` 兜底；
- `resolve_for_agent` 只返回运行期快照，不触碰 HTTP / Trace。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.skills import SkillDefinition, SkillToolRef
from app.core.enums import RiskLevel, SkillStatus, SkillVisibility
from app.core.errors import AppError
from app.db.models import Agent as AgentRow
from app.mcp.schemas import ToolDefinition
from app.models.mcp import McpServer, McpTool
from app.models.skill import AgentSkill, Skill, SkillTool
from app.models.user import AppUser
from app.schemas.skill import (
    AgentSkillBind,
    AgentSkillRead,
    SkillCreate,
    SkillExport,
    SkillExportPayload,
    SkillExportTool,
    SkillRead,
    SkillToolBind,
    SkillToolRead,
    SkillUpdate,
)
from app.services.skill_service import parameters_from_schema, slugify, validate_params

_NON_NULLABLE_UPDATE_FIELDS = {
    "name",
    "slug",
    "summary",
    "category",
    "version",
    "visibility",
    "instructions",
    "input_schema",
    "tags",
}


class SkillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    async def get_visible(self, *, owner_id: int, skill_id: int) -> SkillRead:
        """详情：自己的 Skill，或公开且已发布的 Skill。"""
        skill = (
            await self._session.execute(
                select(Skill).where(
                    Skill.id == skill_id,
                    or_(
                        Skill.owner_id == owner_id,
                        and_(
                            Skill.visibility == SkillVisibility.PUBLIC.value,
                            Skill.status == SkillStatus.PUBLISHED.value,
                        ),
                    ),
                )
            )
        ).scalar_one_or_none()
        if skill is None:
            raise _skill_not_found(skill_id)
        return await self._to_read(skill, owner_id=owner_id)

    async def list_mine(
        self,
        *,
        owner_id: int,
        page: int,
        page_size: int,
        visibility: SkillVisibility | None = None,
        status: SkillStatus | None = None,
        category: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[SkillRead], int]:
        conditions = [Skill.owner_id == owner_id]
        if visibility is not None:
            conditions.append(Skill.visibility == visibility.value)
        if status is not None:
            conditions.append(Skill.status == status.value)
        if category:
            conditions.append(Skill.category == category)
        if keyword:
            pattern = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    Skill.name.ilike(pattern),
                    Skill.slug.ilike(pattern),
                    Skill.summary.ilike(pattern),
                )
            )

        total = int(
            (
                await self._session.execute(
                    select(func.count()).select_from(Skill).where(*conditions)
                )
            ).scalar_one()
        )
        rows = (
            (
                await self._session.execute(
                    select(Skill)
                    .where(*conditions)
                    .order_by(Skill.updated_at.desc(), Skill.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        tools = await self._bulk_tools([row.id for row in rows])
        return [await self._to_read(row, owner_id=owner_id, tools=tools.get(row.id)) for row in rows], total

    async def list_center(
        self,
        *,
        owner_id: int,
        page: int,
        page_size: int,
        category: str | None = None,
        keyword: str | None = None,
        sort: str = "latest",
    ) -> tuple[list[SkillRead], int]:
        conditions = [
            Skill.visibility == SkillVisibility.PUBLIC.value,
            Skill.status == SkillStatus.PUBLISHED.value,
        ]
        if category:
            conditions.append(Skill.category == category)
        if keyword:
            pattern = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    Skill.name.ilike(pattern),
                    Skill.slug.ilike(pattern),
                    Skill.summary.ilike(pattern),
                )
            )

        total = int(
            (
                await self._session.execute(
                    select(func.count()).select_from(Skill).where(*conditions)
                )
            ).scalar_one()
        )
        stmt = select(Skill).where(*conditions)
        if sort == "popular":
            stmt = stmt.order_by(
                Skill.install_count.desc(),
                Skill.like_count.desc(),
                Skill.updated_at.desc(),
            )
        else:
            stmt = stmt.order_by(Skill.updated_at.desc(), Skill.id.desc())
        rows = (
            (await self._session.execute(stmt.offset((page - 1) * page_size).limit(page_size)))
            .scalars()
            .all()
        )
        tools = await self._bulk_tools([row.id for row in rows])
        return [await self._to_read(row, owner_id=owner_id, tools=tools.get(row.id)) for row in rows], total

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    async def create(self, *, owner_id: int, data: SkillCreate) -> SkillRead:
        parameters_from_schema(data.input_schema)  # 契约校验，失败抛 SKILL_INVALID_PARAMS
        await self._validate_tool_ids([bind.tool_id for bind in data.tools])

        slug = await self._unique_slug(owner_id, data.slug or slugify(data.name))
        skill = Skill(
            owner_id=owner_id,
            name=data.name,
            slug=slug,
            summary=data.summary,
            category=data.category.value,
            icon=data.icon,
            version=data.version,
            visibility=data.visibility.value,
            status=SkillStatus.DRAFT.value,
            instructions=data.instructions,
            input_schema=data.input_schema,
            tags=data.tags,
        )
        self._session.add(skill)
        await self._session.flush()

        self._append_tools(skill.id, data.tools)
        await self._session.flush()
        await self._session.refresh(skill)
        return await self._to_read(skill, owner_id=owner_id)

    async def update(self, *, owner_id: int, skill_id: int, data: SkillUpdate) -> SkillRead:
        skill = await self._get_owned(owner_id, skill_id)

        payload = data.model_dump(exclude_unset=True)
        # `tools` 需要保留原始 Pydantic 对象（model_dump 会把它们变成 dict）
        tools = data.tools if "tools" in data.model_fields_set else None
        payload.pop("tools", None)
        if "input_schema" in payload:
            parameters_from_schema(payload["input_schema"])
        if "slug" in payload and payload["slug"] != skill.slug:
            await self._ensure_slug_free(owner_id, payload["slug"] or "")

        for field, value in payload.items():
            if value is None and field in _NON_NULLABLE_UPDATE_FIELDS:
                raise AppError(
                    "INVALID_ARGUMENT", f"字段 {field} 不能为 null", http_status=400
                )
            if hasattr(value, "value"):  # StrEnum -> 存储值
                value = value.value
            setattr(skill, field, value)

        if tools is not None:
            await self._validate_tool_ids([bind.tool_id for bind in tools])
            await self._session.execute(delete(SkillTool).where(SkillTool.skill_id == skill.id))
            self._append_tools(skill.id, tools)

        await self._session.flush()
        await self._session.refresh(skill)
        return await self._to_read(skill, owner_id=owner_id)

    async def delete(self, *, owner_id: int, skill_id: int) -> None:
        skill = await self._get_owned(owner_id, skill_id)
        in_use = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(AgentSkill)
                    .where(AgentSkill.skill_id == skill_id)
                )
            ).scalar_one()
        )
        if in_use:
            raise AppError(
                "SKILL_IN_USE",
                f"Skill 仍被 {in_use} 个 Agent 挂载，请先解除挂载",
                http_status=409,
                detail={"agent_count": in_use},
            )
        await self._session.execute(delete(Skill).where(Skill.id == skill.id))

    async def publish(self, *, owner_id: int, skill_id: int) -> SkillRead:
        skill = await self._get_owned(owner_id, skill_id)
        if not (skill.instructions or "").strip():
            raise AppError(
                "SKILL_INVALID_PARAMS",
                "发布前必须填写 Skill 指令（instructions）",
                http_status=400,
            )
        parameters_from_schema(skill.input_schema)
        missing = await self._missing_required_tools(skill.id)
        if missing:
            raise AppError(
                "SKILL_TOOL_MISSING",
                "Skill 依赖的必填工具当前不可用",
                http_status=409,
                detail={"tools": missing},
            )

        skill.visibility = SkillVisibility.PUBLIC.value
        skill.status = SkillStatus.PUBLISHED.value
        await self._session.flush()
        await self._session.refresh(skill)
        return await self._to_read(skill, owner_id=owner_id)

    async def archive(self, *, owner_id: int, skill_id: int) -> SkillRead:
        skill = await self._get_owned(owner_id, skill_id)
        skill.status = SkillStatus.ARCHIVED.value
        await self._session.flush()
        await self._session.refresh(skill)
        return await self._to_read(skill, owner_id=owner_id)

    async def install(self, *, user_id: int, skill_id: int) -> SkillRead:
        source = (
            await self._session.execute(
                select(Skill).where(
                    Skill.id == skill_id,
                    Skill.visibility == SkillVisibility.PUBLIC.value,
                    Skill.status == SkillStatus.PUBLISHED.value,
                )
            )
        ).scalar_one_or_none()
        if source is None:
            raise _skill_not_found(skill_id)
        if source.owner_id == user_id:
            raise AppError(
                "SKILL_ALREADY_INSTALLED", "不能安装自己创建的 Skill", http_status=409
            )
        existing = (
            await self._session.execute(
                select(Skill.id).where(
                    Skill.owner_id == user_id, Skill.slug == source.slug
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise AppError(
                "SKILL_ALREADY_INSTALLED",
                f"已安装同名 Skill：{source.slug}",
                http_status=409,
            )

        copy = Skill(
            owner_id=user_id,
            name=source.name,
            slug=source.slug,
            summary=source.summary,
            category=source.category,
            icon=source.icon,
            version=source.version,
            visibility=SkillVisibility.PRIVATE.value,
            status=SkillStatus.DRAFT.value,
            instructions=source.instructions,
            input_schema=dict(source.input_schema or {}),
            tags=list(source.tags or []),
        )
        self._session.add(copy)
        await self._session.flush()

        tool_ids = (
            (
                await self._session.execute(
                    select(SkillTool).where(SkillTool.skill_id == source.id)
                )
            )
            .scalars()
            .all()
        )
        for row in tool_ids:
            self._session.add(
                SkillTool(skill_id=copy.id, tool_id=row.tool_id, required=row.required)
            )

        # 计数使用原子自增，避免并发安装丢更新（§8 一致性）
        await self._session.execute(
            update(Skill)
            .where(Skill.id == source.id)
            .values(install_count=Skill.install_count + 1)
        )
        await self._session.flush()
        await self._session.refresh(copy)
        return await self._to_read(copy, owner_id=user_id)

    async def export(self, *, owner_id: int, skill_id: int) -> SkillExport:
        skill = await self._get_owned(owner_id, skill_id)
        tools = await self._bulk_tools([skill.id])
        return SkillExport(
            exported_at=datetime.now(UTC),
            skill=SkillExportPayload(
                name=skill.name,
                slug=skill.slug,
                summary=skill.summary,
                category=skill.category,  # type: ignore[arg-type]
                icon=skill.icon,
                version=skill.version,
                instructions=skill.instructions,
                input_schema=dict(skill.input_schema or {}),
                tags=list(skill.tags or []),
                tools=[
                    SkillExportTool(
                        qualified_name=tool.qualified_name,
                        server_name=tool.server_name,
                        required=tool.required,
                    )
                    for tool in tools.get(skill.id, [])
                ],
            ),
        )

    # ------------------------------------------------------------------
    # Agent 挂载
    # ------------------------------------------------------------------

    async def agent_skills(self, *, agent_id: int) -> list[AgentSkillRead]:
        rows = (
            await self._session.execute(
                select(AgentSkill, Skill)
                .join(Skill, Skill.id == AgentSkill.skill_id)
                .where(AgentSkill.agent_id == agent_id)
                .order_by(AgentSkill.order_no, AgentSkill.skill_id)
            )
        ).all()
        tools = await self._bulk_tools([skill.id for _, skill in rows])
        return [
            _to_agent_skill_read(link, skill, tools.get(skill.id, []))  # type: ignore[arg-type]
            for link, skill in rows
        ]

    async def replace_agent_skills(
        self,
        *,
        agent_id: int,
        owner_id: int,
        binds: list[AgentSkillBind],
    ) -> list[AgentSkillRead]:
        await self._ensure_agent(agent_id)

        # 同一 Skill 只允许挂载一次；后出现的声明覆盖前者
        unique: dict[int, AgentSkillBind] = {}
        for bind in binds:
            unique[bind.skill_id] = bind

        skills: dict[int, Skill] = {}
        if unique:
            rows = (
                (
                    await self._session.execute(
                        select(Skill).where(
                            Skill.id.in_(sorted(unique)),
                            Skill.owner_id == owner_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            skills = {row.id: row for row in rows}
            missing = sorted(set(unique) - set(skills))
            if missing:
                raise AppError(
                    "SKILL_NOT_FOUND",
                    "挂载的 Skill 不存在或不属于当前用户",
                    http_status=404,
                    detail={"skill_ids": missing},
                )

        for skill_id, bind in unique.items():
            parameters = parameters_from_schema(skills[skill_id].input_schema)
            validate_params(parameters, bind.params)

        await self._session.execute(delete(AgentSkill).where(AgentSkill.agent_id == agent_id))
        for skill_id, bind in unique.items():
            self._session.add(
                AgentSkill(
                    agent_id=agent_id,
                    skill_id=skill_id,
                    order_no=bind.order_no,
                    enabled=bind.enabled,
                    params=bind.params,
                )
            )
        await self._session.flush()
        return await self.agent_skills(agent_id=agent_id)

    async def resolve_for_agent(self, *, agent_id: int) -> list[SkillDefinition]:
        """运行期解析：返回按 `order_no` 排序的 Skill 快照（含工具可用性）。"""
        rows = (
            await self._session.execute(
                select(AgentSkill, Skill)
                .join(Skill, Skill.id == AgentSkill.skill_id)
                .where(AgentSkill.agent_id == agent_id, AgentSkill.enabled.is_(True))
                .order_by(AgentSkill.order_no, AgentSkill.skill_id)
            )
        ).all()

        definitions: list[SkillDefinition] = []
        for link, skill in rows:
            tool_rows = (
                await self._session.execute(
                    select(SkillTool, McpTool, McpServer.name)
                    .join(McpTool, McpTool.id == SkillTool.tool_id)
                    .join(McpServer, McpServer.id == McpTool.server_id)
                    .where(SkillTool.skill_id == skill.id)
                    .order_by(McpTool.id)
                )
            ).all()
            refs = [
                SkillToolRef(
                    qualified_name=mcp_tool.qualified_name,
                    required=binding.required,
                    tool=_to_definition(mcp_tool, server_name) if mcp_tool.enabled else None,
                )
                for binding, mcp_tool, server_name in tool_rows
            ]
            definitions.append(
                SkillDefinition(
                    id=skill.id,
                    slug=skill.slug,
                    name=skill.name,
                    version=skill.version,
                    instructions=skill.instructions,
                    parameters=parameters_from_schema(skill.input_schema),
                    values=dict(link.params or {}),
                    tools=refs,
                    enabled=True,
                    order_no=link.order_no,
                )
            )
        return definitions

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _get_owned(self, owner_id: int, skill_id: int) -> Skill:
        skill = (
            await self._session.execute(
                select(Skill).where(Skill.id == skill_id, Skill.owner_id == owner_id)
            )
        ).scalar_one_or_none()
        if skill is None:
            raise _skill_not_found(skill_id)
        return skill

    async def _ensure_agent(self, agent_id: int) -> None:
        exists = (
            await self._session.execute(
                select(AgentRow.id).where(AgentRow.id == agent_id, AgentRow.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if exists is None:
            raise AppError("NOT_FOUND", f"Agent 不存在：{agent_id}", http_status=404)

    async def _unique_slug(self, owner_id: int, base: str) -> str:
        base = (base or "skill")[:80].strip("-") or "skill"
        candidate = base
        suffix = 2
        while await self._slug_exists(owner_id, candidate):
            tail = f"-{suffix}"
            candidate = f"{base[: 80 - len(tail)]}{tail}"
            suffix += 1
        return candidate

    async def _ensure_slug_free(self, owner_id: int, slug: str) -> None:
        if not slug:
            raise AppError("INVALID_ARGUMENT", "slug 不能为空", http_status=400)
        if await self._slug_exists(owner_id, slug):
            raise AppError(
                "CONFLICT", f"slug 已存在：{slug}", http_status=409
            )

    async def _slug_exists(self, owner_id: int, slug: str) -> bool:
        found = (
            await self._session.execute(
                select(Skill.id).where(Skill.owner_id == owner_id, Skill.slug == slug)
            )
        ).scalar_one_or_none()
        return found is not None

    def _append_tools(self, skill_id: int, binds: list[SkillToolBind]) -> None:
        seen: set[int] = set()
        for bind in binds:
            if bind.tool_id in seen:
                continue
            seen.add(bind.tool_id)
            self._session.add(
                SkillTool(skill_id=skill_id, tool_id=bind.tool_id, required=bind.required)
            )

    async def _validate_tool_ids(self, tool_ids: list[int]) -> None:
        unique = sorted(set(tool_ids))
        if not unique:
            return
        found = set(
            (
                await self._session.execute(select(McpTool.id).where(McpTool.id.in_(unique)))
            )
            .scalars()
            .all()
        )
        missing = [tool_id for tool_id in unique if tool_id not in found]
        if missing:
            raise AppError(
                "TOOL_NOT_FOUND",
                "Skill 绑定的 Tool 不存在",
                http_status=404,
                detail={"tool_ids": missing},
            )

    async def _missing_required_tools(self, skill_id: int) -> list[str]:
        rows = (
            await self._session.execute(
                select(McpTool.qualified_name, McpTool.enabled)
                .join(SkillTool, SkillTool.tool_id == McpTool.id)
                .where(SkillTool.skill_id == skill_id, SkillTool.required.is_(True))
            )
        ).all()
        return [qualified_name for qualified_name, enabled in rows if not enabled]

    async def _bulk_tools(
        self, skill_ids: list[int]
    ) -> dict[int, list[SkillToolRead]]:
        if not skill_ids:
            return {}
        rows = (
            await self._session.execute(
                select(SkillTool.skill_id, SkillTool.required, McpTool, McpServer.name)
                .join(McpTool, McpTool.id == SkillTool.tool_id)
                .join(McpServer, McpServer.id == McpTool.server_id)
                .where(SkillTool.skill_id.in_(skill_ids))
                .order_by(McpTool.id)
            )
        ).all()
        result: dict[int, list[SkillToolRead]] = {}
        for skill_id, required, tool, server_name in rows:
            result.setdefault(skill_id, []).append(
                SkillToolRead(
                    tool_id=tool.id,
                    qualified_name=tool.qualified_name,
                    server_name=server_name,
                    description=tool.description,
                    required=required,
                    enabled=tool.enabled,
                )
            )
        return result

    async def _to_read(
        self,
        skill: Skill,
        *,
        owner_id: int,
        tools: list[SkillToolRead] | None = None,
    ) -> SkillRead:
        if tools is None:
            tools = (await self._bulk_tools([skill.id])).get(skill.id, [])
        owner_display_name = (
            await self._session.execute(
                select(AppUser.display_name).where(AppUser.id == skill.owner_id)
            )
        ).scalar_one_or_none()
        return SkillRead(
            id=skill.id,
            owner_id=skill.owner_id,
            owner_display_name=owner_display_name,
            name=skill.name,
            slug=skill.slug,
            summary=skill.summary,
            category=skill.category,  # type: ignore[arg-type]
            icon=skill.icon,
            version=skill.version,
            visibility=skill.visibility,  # type: ignore[arg-type]
            status=skill.status,  # type: ignore[arg-type]
            instructions=skill.instructions,
            input_schema=dict(skill.input_schema or {}),
            tags=list(skill.tags or []),
            install_count=skill.install_count,
            like_count=skill.like_count,
            tools=tools,
            owned=skill.owner_id == owner_id,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
        )


def _to_agent_skill_read(
    link: AgentSkill, skill: Skill, tools: list[SkillToolRead]
) -> AgentSkillRead:
    return AgentSkillRead(
        skill_id=skill.id,
        name=skill.name,
        slug=skill.slug,
        version=skill.version,
        status=skill.status,  # type: ignore[arg-type]
        visibility=skill.visibility,  # type: ignore[arg-type]
        order_no=link.order_no,
        enabled=link.enabled,
        params=dict(link.params or {}),
        tools=tools,
    )


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


def _skill_not_found(skill_id: int) -> AppError:
    return AppError("SKILL_NOT_FOUND", f"Skill 不存在：{skill_id}", http_status=404)
