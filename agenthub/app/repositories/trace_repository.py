"""Trace 仓储。数据库设计文档 §6.6。归属：D（Platform Backend）。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import StepStatus, TraceEventType
from app.db.models import AgentStep
from app.schemas.run import StepRead
from app.trace.events import TraceEvent


class TraceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, event: TraceEvent) -> int:
        row = AgentStep(
            run_id=event.run_id,
            step_no=event.step_no,
            event_type=event.event_type.value,
            status=event.status.value,
            node=event.node,
            tool=event.tool,
            duration_ms=event.duration_ms,
            payload=event.data,
            created_at=event.timestamp,
        )
        self._session.add(row)
        await self._session.flush()
        return row.id

    async def list_steps(
        self,
        *,
        run_id: str,
        page: int,
        page_size: int,
        after_step_no: int | None = None,
    ) -> tuple[list[StepRead], int]:
        conditions = [AgentStep.run_id == run_id]
        if after_step_no is not None:
            conditions.append(AgentStep.step_no > after_step_no)

        total = int(
            (
                await self._session.execute(
                    select(func.count()).select_from(AgentStep).where(*conditions)
                )
            ).scalar_one()
        )
        rows = (
            (
                await self._session.execute(
                    select(AgentStep)
                    .where(*conditions)
                    .order_by(AgentStep.step_no.asc(), AgentStep.id.asc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return [_to_step_read(row) for row in rows], total

    async def list_all_after(self, *, run_id: str, after_id: int) -> list[StepRead]:
        rows = (
            (
                await self._session.execute(
                    select(AgentStep)
                    .where(AgentStep.run_id == run_id, AgentStep.id > after_id)
                    .order_by(AgentStep.step_no.asc(), AgentStep.id.asc())
                )
            )
            .scalars()
            .all()
        )
        return [_to_step_read(row) for row in rows]


def _to_step_read(row: AgentStep) -> StepRead:
    return StepRead(
        id=row.id,
        run_id=row.run_id,
        step_no=row.step_no,
        event_type=TraceEventType(row.event_type),
        status=StepStatus(row.status),
        node=row.node,
        tool=row.tool,
        duration_ms=row.duration_ms,
        payload=row.payload or {},
        created_at=row.created_at,
    )
