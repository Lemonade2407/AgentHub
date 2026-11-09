"""Agent 仓储。数据库设计文档 §6.1。归属：D（Platform Backend）。"""

from __future__ import annotations

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import Agent, AgentTool, McpTool
from app.schemas.agent import AgentCreate, AgentRead, AgentUpdate

_NON_NULLABLE_UPDATE_FIELDS = {"name", "model", "system_prompt", "max_steps", "enabled"}


class AgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: AgentCreate) -> AgentRead:
        await self._validate_tool_ids(data.tool_ids)

        agent = Agent(
            name=data.name,
            description=data.description,
            model=data.model,
            system_prompt=data.system_prompt,
            max_steps=data.max_steps,
            enabled=data.enabled,
        )
        self._session.add(agent)
        await self._session.flush()

        for tool_id in sorted(set(data.tool_ids)):
            self._session.add(AgentTool(agent_id=agent.id, tool_id=tool_id))
        await self._session.flush()
        return await self._to_read(agent)

    async def get(self, agent_id: int, *, include_deleted: bool = False) -> AgentRead:
        agent = await self.get_raw(agent_id, include_deleted=include_deleted)
        if agent is None:
            raise AppError("NOT_FOUND", f"Agent 不存在：{agent_id}", http_status=404)
        return await self._to_read(agent)

    async def get_raw(self, agent_id: int, *, include_deleted: bool = False) -> Agent | None:
        stmt = select(Agent).where(Agent.id == agent_id)
        if not include_deleted:
            stmt = stmt.where(Agent.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        enabled: bool | None = None,
        keyword: str | None = None,
    ) -> tuple[list[AgentRead], int]:
        conditions = [Agent.deleted_at.is_(None)]
        if enabled is not None:
            conditions.append(Agent.enabled.is_(enabled))
        if keyword:
            pattern = f"%{keyword}%"
            conditions.append(
                or_(Agent.name.ilike(pattern), Agent.description.ilike(pattern))
            )

        total = int(
            (
                await self._session.execute(
                    select(func.count()).select_from(Agent).where(*conditions)
                )
            ).scalar_one()
        )
        rows = (
            (
                await self._session.execute(
                    select(Agent)
                    .where(*conditions)
                    .order_by(Agent.created_at.desc(), Agent.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return [await self._to_read(row) for row in rows], total

    async def update(self, agent_id: int, data: AgentUpdate) -> AgentRead:
        agent = await self.get_raw(agent_id)
        if agent is None:
            raise AppError("NOT_FOUND", f"Agent 不存在：{agent_id}", http_status=404)

        payload = data.model_dump(exclude_unset=True)
        for field, value in payload.items():
            if value is None and field in _NON_NULLABLE_UPDATE_FIELDS:
                raise AppError(
                    "INVALID_ARGUMENT", f"字段 {field} 不能为 null", http_status=400
                )
            setattr(agent, field, value)

        await self._session.flush()
        await self._session.refresh(agent)
        return await self._to_read(agent)

    async def soft_delete(self, agent_id: int) -> None:
        agent = await self.get_raw(agent_id)
        if agent is None:
            raise AppError("NOT_FOUND", f"Agent 不存在：{agent_id}", http_status=404)
        if agent.deleted_at is None:
            from app.db.models import utcnow

            agent.deleted_at = utcnow()
            await self._session.flush()

    async def bind_tools(self, agent_id: int, tool_ids: list[int]) -> AgentRead:
        agent = await self.get_raw(agent_id)
        if agent is None:
            raise AppError("NOT_FOUND", f"Agent 不存在：{agent_id}", http_status=404)

        unique_ids = sorted(set(tool_ids))
        await self._validate_tool_ids(unique_ids)

        await self._session.execute(delete(AgentTool).where(AgentTool.agent_id == agent_id))
        for tool_id in unique_ids:
            self._session.add(AgentTool(agent_id=agent_id, tool_id=tool_id))
        await self._session.flush()
        return await self._to_read(agent)

    async def count_enabled_tools(self, agent_id: int) -> int:
        return int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(AgentTool)
                    .join(McpTool, McpTool.id == AgentTool.tool_id)
                    .where(AgentTool.agent_id == agent_id, McpTool.enabled.is_(True))
                )
            ).scalar_one()
        )

    async def _validate_tool_ids(self, tool_ids: list[int]) -> None:
        unique_ids = sorted(set(tool_ids))
        if not unique_ids:
            return
        found = set(
            (
                await self._session.execute(select(McpTool.id).where(McpTool.id.in_(unique_ids)))
            )
            .scalars()
            .all()
        )
        missing = [tool_id for tool_id in unique_ids if tool_id not in found]
        if missing:
            raise AppError(
                "TOOL_NOT_FOUND",
                "引用的 Tool 不存在",
                http_status=404,
                detail={"tool_ids": missing},
            )

    async def _to_read(self, agent: Agent) -> AgentRead:
        tool_ids = (
            (
                await self._session.execute(
                    select(AgentTool.tool_id)
                    .where(AgentTool.agent_id == agent.id)
                    .order_by(AgentTool.tool_id)
                )
            )
            .scalars()
            .all()
        )
        return AgentRead(
            id=agent.id,
            name=agent.name,
            description=agent.description,
            model=agent.model,
            system_prompt=agent.system_prompt,
            max_steps=agent.max_steps,
            enabled=agent.enabled,
            tool_ids=list(tool_ids),
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )
