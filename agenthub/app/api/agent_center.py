"""Agent Center 预检与安装 API（修改意见文档 §5.5，WP-3.3）。

归属：B（依赖解析）+ D（平台接口）。当前只实现预检与安装；
发布、广场、点赞、下架等属于 WP-3.1 / WP-3.5，后续接入。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_session
from app.models.user import AppUser
from app.schemas.agent_center import InstallRead, InstallRequest, PrecheckRead
from app.services.agent_center_service import AgentCenterService

router = APIRouter(prefix="/api/agent-center", tags=["agent-center"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[AppUser, Depends(get_current_user)]


@router.post("/{publication_id}/precheck", response_model=PrecheckRead)
async def precheck(
    publication_id: int,
    session: SessionDep,
    user: CurrentUser,
) -> PrecheckRead:
    """依赖预检：返回缺失的 Skill / MCP Server，不写任何数据。"""
    return await AgentCenterService(session).precheck(
        publication_id=publication_id,
        installer_id=user.id,
    )


@router.post(
    "/{publication_id}/install",
    response_model=InstallRead,
    status_code=status.HTTP_201_CREATED,
)
async def install(
    publication_id: int,
    payload: InstallRequest,
    session: SessionDep,
    user: CurrentUser,
) -> InstallRead:
    """安装为本地 Agent：依赖缺失时默认 409，`confirm_missing=true` 可跳过。"""
    result = await AgentCenterService(session).install(
        publication_id=publication_id,
        installer_id=user.id,
        confirm_missing=payload.confirm_missing,
    )
    await session.commit()
    return result
