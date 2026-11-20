"""Run / Trace 记录保留策略。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RunStatus
from app.models.run import AgentRun

TERMINAL_STATUSES = (
    RunStatus.SUCCESS.value,
    RunStatus.PARTIAL.value,
    RunStatus.FAILED.value,
    RunStatus.CANCELLED.value,
)


async def cleanup_runs(
    session: AsyncSession,
    older_than_days: int,
    *,
    dry_run: bool = False,
) -> tuple[int, int]:
    """删除或统计早于指定天数的终态 Run；返回 (matched, deleted)。

    `agent_step` 通过外键级联删除，不会留下孤儿 Trace。
    """
    days = max(int(older_than_days), 0)
    cutoff = datetime.now(UTC) - timedelta(days=days)
    condition = (
        AgentRun.status.in_(TERMINAL_STATUSES),
        AgentRun.created_at < cutoff,
    )

    matched = int(
        (
            await session.execute(
                select(func.count()).select_from(AgentRun).where(*condition)
            )
        ).scalar_one()
    )
    if dry_run:
        return matched, 0

    result = await session.execute(delete(AgentRun).where(*condition))
    await session.commit()
    return matched, int(result.rowcount or 0)
