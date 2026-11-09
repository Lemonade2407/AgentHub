"""Run 仓储。数据库设计文档 §6.5。归属：D（Platform Backend）。"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runner import RunResult
from app.core.enums import RunStatus, StopReason
from app.db.models import AgentRun
from app.schemas.run import RunRead


class RunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        run_id: str,
        agent_id: int,
        thread_id: str,
        user_input: str,
        max_steps: int,
    ) -> RunRead:
        from app.db.models import utcnow

        run = AgentRun(
            id=run_id,
            agent_id=agent_id,
            thread_id=thread_id,
            status=RunStatus.RUNNING.value,
            input=user_input,
            max_steps=max_steps,
            started_at=utcnow(),
        )
        self._session.add(run)
        await self._session.flush()
        return _to_read(run)

    async def get(self, run_id: str) -> RunRead:
        run = (
            await self._session.execute(select(AgentRun).where(AgentRun.id == run_id))
        ).scalar_one_or_none()
        if run is None:
            from app.core.errors import AppError

            raise AppError("NOT_FOUND", f"Run 不存在：{run_id}", http_status=404)
        return _to_read(run)

    async def list_by_agent(
        self,
        *,
        agent_id: int,
        page: int,
        page_size: int,
        status: RunStatus | None = None,
        sort: str = "-created_at",
    ) -> tuple[list[RunRead], int]:
        conditions = [AgentRun.agent_id == agent_id]
        if status is not None:
            conditions.append(AgentRun.status == status.value)

        total = int(
            (
                await self._session.execute(
                    select(func.count()).select_from(AgentRun).where(*conditions)
                )
            ).scalar_one()
        )

        order = AgentRun.created_at.asc() if not sort.startswith("-") else AgentRun.created_at.desc()
        rows = (
            (
                await self._session.execute(
                    select(AgentRun)
                    .where(*conditions)
                    .order_by(order, AgentRun.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return [_to_read(row) for row in rows], total

    async def finish(self, run_id: str, result: RunResult) -> None:
        from app.db.models import utcnow

        await self._session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.status.in_([RunStatus.PENDING.value, RunStatus.RUNNING.value]),
            )
            .values(
                status=result.status.value,
                stop_reason=result.stop_reason.value,
                output=result.output,
                error_code=result.error_code,
                error_message=result.error_message,
                llm_calls=result.llm_calls,
                tool_calls=result.tool_calls,
                step_count=result.step_count,
                duration_ms=result.duration_ms,
                finished_at=utcnow(),
            )
        )


def _to_read(run: AgentRun) -> RunRead:
    return RunRead(
        id=run.id,
        agent_id=run.agent_id,
        thread_id=run.thread_id,
        status=RunStatus(run.status),
        stop_reason=StopReason(run.stop_reason) if run.stop_reason else None,
        input=run.input,
        output=run.output,
        error_code=run.error_code,
        error_message=run.error_message,
        max_steps=run.max_steps,
        llm_calls=run.llm_calls,
        tool_calls=run.tool_calls,
        step_count=run.step_count,
        duration_ms=run.duration_ms,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )
