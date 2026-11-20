"""Agent Center 发布快照与广场服务。归属：D（Platform Backend）。

对应修改意见 §5.1 / §5.5：
- 发布生成不可变、已脱敏的快照（`build_agent_snapshot` 白名单）；
- 广场只展示 `published`，支持关键词 / 分类 / 最新 / 最热；
- 点赞幂等、计数原子更新；作者可下架。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.skills import SkillDefinition
from app.agent.snapshot import (
    SnapshotError,
    SnapshotTool,
    SuggestedModel,
    build_agent_snapshot,
    dump_snapshot,
)
from app.core.enums import PublicationStatus, SkillCategory
from app.core.errors import AppError
from app.db.models import McpServer
from app.models.publication import AgentPublication, PublicationLike
from app.models.user import AppUser
from app.repositories.agent_repository import AgentRepository
from app.repositories.mcp_repository import McpServerRepository, McpToolRepository
from app.repositories.skill_repository import SkillRepository
from app.schemas.agent_center import PublicationCreate, PublicationRead
from app.schemas.agent import AgentRead


class PublicationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # 列表 / 详情
    # ------------------------------------------------------------------

    async def list_center(
        self,
        *,
        page: int,
        page_size: int,
        keyword: str | None = None,
        category: str | None = None,
        sort: str = "latest",
    ) -> tuple[list[PublicationRead], int]:
        conditions = [AgentPublication.status == PublicationStatus.PUBLISHED.value]
        return await self._list(
            conditions=conditions,
            page=page,
            page_size=page_size,
            keyword=keyword,
            category=category,
            sort=sort,
        )

    async def list_mine(
        self,
        *,
        owner_id: int,
        page: int,
        page_size: int,
        keyword: str | None = None,
        category: str | None = None,
        sort: str = "latest",
    ) -> tuple[list[PublicationRead], int]:
        return await self._list(
            conditions=[AgentPublication.owner_id == owner_id],
            page=page,
            page_size=page_size,
            keyword=keyword,
            category=category,
            sort=sort,
        )

    async def _list(
        self,
        *,
        conditions: list,
        page: int,
        page_size: int,
        keyword: str | None,
        category: str | None,
        sort: str,
    ) -> tuple[list[PublicationRead], int]:
        if category:
            conditions.append(AgentPublication.category == category)
        if keyword:
            pattern = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    AgentPublication.title.ilike(pattern),
                    AgentPublication.summary.ilike(pattern),
                )
            )

        total = int(
            (
                await self._session.execute(
                    select(func.count()).select_from(AgentPublication).where(*conditions)
                )
            ).scalar_one()
        )

        stmt = (
            select(AgentPublication, AppUser.display_name)
            .outerjoin(AppUser, AppUser.id == AgentPublication.owner_id)
            .where(*conditions)
        )
        if sort == "popular":
            stmt = stmt.order_by(
                AgentPublication.install_count.desc(),
                AgentPublication.like_count.desc(),
                AgentPublication.id.desc(),
            )
        else:
            stmt = stmt.order_by(
                AgentPublication.published_at.desc().nullslast(),
                AgentPublication.id.desc(),
            )
        rows = (
            await self._session.execute(
                stmt.offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
        return [self._to_read(pub, owner_name) for pub, owner_name in rows], total

    async def get(self, *, publication_id: int, viewer_id: int) -> PublicationRead:
        pub = await self._get(publication_id)
        if (
            pub.status != PublicationStatus.PUBLISHED.value
            and pub.owner_id != viewer_id
        ):
            raise AppError("PUBLICATION_NOT_FOUND", "发布不存在", http_status=404)
        owner_name = (
            await self._session.execute(
                select(AppUser.display_name).where(AppUser.id == pub.owner_id)
            )
        ).scalar_one_or_none()
        return self._to_read(pub, owner_name)

    # ------------------------------------------------------------------
    # 发布 / 下架
    # ------------------------------------------------------------------

    async def publish(
        self,
        *,
        agent_id: int,
        owner_id: int,
        payload: PublicationCreate,
    ) -> PublicationRead:
        agent = await AgentRepository(self._session).get(agent_id)
        skills = await SkillRepository(self._session).resolve_for_agent(agent_id=agent_id)
        tool_deps = await self._collect_tool_dependencies(agent_id, skills)

        try:
            snapshot = build_agent_snapshot(
                agent=agent,
                skills=skills,
                tool_dependencies=tool_deps,
                suggested_model=_suggested_model(agent),
            )
            raw_snapshot = dump_snapshot(snapshot)
        except SnapshotError as exc:
            raise AppError(exc.code, exc.message, http_status=400) from exc

        existing = (
            await self._session.execute(
                select(AgentPublication.id).where(
                    AgentPublication.owner_id == owner_id,
                    AgentPublication.source_agent_id == agent_id,
                    AgentPublication.version == payload.version,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise AppError(
                "CONFLICT",
                f"该 Agent 的版本 {payload.version} 已发布，请修改版本号",
                http_status=409,
            )

        pub = AgentPublication(
            owner_id=owner_id,
            source_agent_id=agent_id,
            title=payload.title,
            summary=payload.summary,
            category=payload.category.value,
            version=payload.version,
            status=PublicationStatus.PUBLISHED.value,
            snapshot=raw_snapshot,
            published_at=datetime.now(UTC),
        )
        self._session.add(pub)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise AppError("CONFLICT", "该版本已发布", http_status=409) from exc
        await self._session.refresh(pub)
        owner_name = (
            await self._session.execute(
                select(AppUser.display_name).where(AppUser.id == owner_id)
            )
        ).scalar_one_or_none()
        return self._to_read(pub, owner_name)

    async def offline(self, *, publication_id: int, owner_id: int) -> PublicationRead:
        pub = await self._get(publication_id)
        if pub.owner_id != owner_id:
            raise AppError(
                "PUBLICATION_FORBIDDEN", "只能下架自己发布的 Agent", http_status=403
            )
        pub.status = PublicationStatus.OFFLINE.value
        await self._session.flush()
        await self._session.refresh(pub)
        owner_name = (
            await self._session.execute(
                select(AppUser.display_name).where(AppUser.id == owner_id)
            )
        ).scalar_one_or_none()
        return self._to_read(pub, owner_name)

    # ------------------------------------------------------------------
    # 点赞
    # ------------------------------------------------------------------

    async def like(self, *, publication_id: int, user_id: int) -> dict[str, object]:
        pub = await self._get(publication_id)
        if pub.status != PublicationStatus.PUBLISHED.value:
            raise AppError("PUBLICATION_OFFLINE", "该发布已下架", http_status=409)
        exists = (
            await self._session.execute(
                select(PublicationLike.publication_id).where(
                    PublicationLike.publication_id == publication_id,
                    PublicationLike.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            self._session.add(
                PublicationLike(publication_id=publication_id, user_id=user_id)
            )
            await self._session.execute(
                update(AgentPublication)
                .where(AgentPublication.id == publication_id)
                .values(like_count=AgentPublication.like_count + 1)
            )
            await self._session.flush()
        count = (
            await self._session.execute(
                select(AgentPublication.like_count).where(
                    AgentPublication.id == publication_id
                )
            )
        ).scalar_one()
        return {"liked": True, "like_count": int(count)}

    async def unlike(self, *, publication_id: int, user_id: int) -> dict[str, object]:
        await self._get(publication_id)
        exists = (
            await self._session.execute(
                select(PublicationLike.publication_id).where(
                    PublicationLike.publication_id == publication_id,
                    PublicationLike.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if exists is not None:
            from sqlalchemy import delete

            await self._session.execute(
                delete(PublicationLike).where(
                    PublicationLike.publication_id == publication_id,
                    PublicationLike.user_id == user_id,
                )
            )
            await self._session.execute(
                update(AgentPublication)
                .where(AgentPublication.id == publication_id)
                .values(like_count=func.greatest(AgentPublication.like_count - 1, 0))
            )
            await self._session.flush()
        count = (
            await self._session.execute(
                select(AgentPublication.like_count).where(
                    AgentPublication.id == publication_id
                )
            )
        ).scalar_one()
        return {"liked": False, "like_count": int(count)}

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _get(self, publication_id: int) -> AgentPublication:
        pub = (
            await self._session.execute(
                select(AgentPublication).where(AgentPublication.id == publication_id)
            )
        ).scalar_one_or_none()
        if pub is None:
            raise AppError(
                "PUBLICATION_NOT_FOUND",
                f"Publication 不存在：{publication_id}",
                http_status=404,
            )
        return pub

    async def _collect_tool_dependencies(
        self, agent_id: int, skills: list[SkillDefinition]
    ) -> list[SnapshotTool]:
        deps: dict[tuple[str, str], SnapshotTool] = {}
        server_ids: dict[tuple[str, str], int | None] = {}

        def add(
            *,
            server_name: str,
            remote_name: str,
            required: bool,
            server_id: int | None = None,
        ) -> None:
            key = (server_name, remote_name)
            existing = deps.get(key)
            if existing is not None:
                if required and not existing.required:
                    existing.required = True
                return
            deps[key] = SnapshotTool(
                server_name=server_name,
                remote_name=remote_name,
                required=required,
                transport=None,
                endpoint=None,
            )
            server_ids[key] = server_id

        for tool in await McpToolRepository(self._session).list_bound_tools(agent_id=agent_id):
            add(
                server_name=tool.server_name,
                remote_name=tool.remote_name,
                required=True,
                server_id=tool.server_id,
            )
        for skill in skills:
            for ref in skill.tools:
                tool = ref.tool
                if tool is not None:
                    add(
                        server_name=tool.server_name,
                        remote_name=tool.remote_name,
                        required=ref.required,
                        server_id=tool.server_id,
                    )
                else:
                    server_name, _, remote_name = ref.qualified_name.partition(".")
                    add(
                        server_name=server_name or ref.qualified_name,
                        remote_name=remote_name or ref.qualified_name,
                        required=ref.required,
                    )

        # 补齐 transport / endpoint；快照只写 endpoint，不写 headers
        server_cache: dict[int, McpServer | None] = {}
        server_by_name: dict[str, McpServer | None] = {}
        for key, dep in deps.items():
            server_id = server_ids.get(key)
            server: McpServer | None = None
            if server_id is not None:
                if server_id not in server_cache:
                    server_cache[server_id] = await McpServerRepository(self._session).get_raw(server_id)
                server = server_cache[server_id]
            else:
                if dep.server_name not in server_by_name:
                    server_by_name[dep.server_name] = (
                        await self._session.execute(
                            select(McpServer).where(McpServer.name == dep.server_name)
                        )
                    ).scalar_one_or_none()
                server = server_by_name[dep.server_name]
            if server is not None:
                dep.transport = server.transport
                dep.endpoint = server.endpoint
        return list(deps.values())

    def _to_read(
        self, pub: AgentPublication, owner_name: str | None
    ) -> PublicationRead:
        return PublicationRead(
            id=pub.id,
            title=pub.title,
            summary=pub.summary,
            category=pub.category,  # type: ignore[arg-type]
            version=pub.version,
            status=pub.status,
            owner_id=pub.owner_id,
            owner_display_name=owner_name,
            install_count=pub.install_count,
            like_count=pub.like_count,
            published_at=pub.published_at,
            created_at=pub.created_at,
            snapshot=dict(pub.snapshot or {}),
        )


def _suggested_model(agent: AgentRead) -> SuggestedModel | None:
    model = (agent.model or "").strip()
    if not model:
        return None
    provider, _, model_key = model.partition("/")
    if not provider or not model_key:
        return SuggestedModel(provider="custom", model_key=model)
    return SuggestedModel(provider=provider, model_key=model_key)
