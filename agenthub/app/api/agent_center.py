"""Agent Center 预检与安装 API（修改意见文档 §5.5，WP-3.3）。

归属：B（依赖解析）+ D（平台接口）。当前只实现预检与安装；
发布、广场、点赞、下架等属于 WP-3.1 / WP-3.5，后续接入。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_session
from app.models.user import AppUser
from app.schemas.agent_center import (
    InstallRead,
    InstallRequest,
    PrecheckRead,
    PublicationCreate,
    PublicationRead,
)
from app.schemas.common import Page
from app.services.agent_center_service import AgentCenterService
from app.services.publication_service import PublicationService

router = APIRouter(prefix="/api/agent-center", tags=["agent-center"])
agent_router = APIRouter(prefix="/api/agents", tags=["agent-center"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[AppUser, Depends(get_current_user)]


# ----------------------------------------------------------------------
# 广场 / 我的发布 / 详情
# ----------------------------------------------------------------------


@router.get("", response_model=Page[PublicationRead])
async def list_center(
    session: SessionDep,
    user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=100),
    keyword: str | None = None,
    category: str | None = None,
    sort: str = Query(default="latest", pattern="^(latest|popular)$"),
) -> Page[PublicationRead]:
    items, total = await PublicationService(session).list_center(
        page=page,
        page_size=page_size,
        keyword=keyword,
        category=category,
        sort=sort,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/mine", response_model=Page[PublicationRead])
async def list_mine(
    session: SessionDep,
    user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=100),
    keyword: str | None = None,
    category: str | None = None,
    sort: str = Query(default="latest", pattern="^(latest|popular)$"),
) -> Page[PublicationRead]:
    items, total = await PublicationService(session).list_mine(
        owner_id=user.id,
        page=page,
        page_size=page_size,
        keyword=keyword,
        category=category,
        sort=sort,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{publication_id}", response_model=PublicationRead)
async def get_publication(
    publication_id: int, session: SessionDep, user: CurrentUser
) -> PublicationRead:
    return await PublicationService(session).get(
        publication_id=publication_id, viewer_id=user.id
    )


@router.post("/{publication_id}/offline", response_model=PublicationRead)
async def offline_publication(
    publication_id: int, session: SessionDep, user: CurrentUser
) -> PublicationRead:
    pub = await PublicationService(session).offline(
        publication_id=publication_id, owner_id=user.id
    )
    await session.commit()
    return pub


@router.post("/{publication_id}/like")
async def like_publication(
    publication_id: int, session: SessionDep, user: CurrentUser
) -> dict[str, object]:
    result = await PublicationService(session).like(
        publication_id=publication_id, user_id=user.id
    )
    await session.commit()
    return result


@router.post("/{publication_id}/unlike")
async def unlike_publication(
    publication_id: int, session: SessionDep, user: CurrentUser
) -> dict[str, object]:
    result = await PublicationService(session).unlike(
        publication_id=publication_id, user_id=user.id
    )
    await session.commit()
    return result


# ----------------------------------------------------------------------
# 发布
# ----------------------------------------------------------------------


@agent_router.post("/{agent_id}/publish", response_model=PublicationRead)
async def publish_agent(
    agent_id: int,
    payload: PublicationCreate,
    session: SessionDep,
    user: CurrentUser,
) -> PublicationRead:
    pub = await PublicationService(session).publish(
        agent_id=agent_id, owner_id=user.id, payload=payload
    )
    await session.commit()
    return pub


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
