"""维护接口：清理历史 Run / Trace。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.retention_service import cleanup_runs

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("/runs/cleanup")
async def cleanup_old_runs(
    session: SessionDep,
    older_than_days: int = Query(default=30, ge=0, le=3650),
    dry_run: bool = Query(default=False),
) -> dict[str, int | bool]:
    """清理早于 N 天的终态 Run；`older_than_days=0` 表示全部终态记录。"""
    matched, deleted = await cleanup_runs(
        session, older_than_days, dry_run=dry_run
    )
    return {
        "older_than_days": older_than_days,
        "dry_run": dry_run,
        "matched": matched,
        "deleted": deleted,
    }
