"""Skills Center API（修改意见文档 §4.5，Contract v2.0）。

归属：D（Platform Backend）。包含两组路由：

- `/api/skills`：Skill CRUD、发布 / 下架、广场、安装、导出；
- `/api/agents/{id}/skills`：Agent 挂载 Skill（全量覆盖，含顺序与参数覆盖）。

权限：所有读写均按当前用户 `owner_id` 收敛；跨用户访问公开 Skill 时仅可读与安装。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.skills import SkillValidationError
from app.api.deps import get_current_user
from app.core.enums import SkillCategory, SkillStatus, SkillVisibility
from app.core.errors import AppError
from app.db.session import get_session
from app.models.user import AppUser
from app.repositories.skill_repository import SkillRepository
from app.schemas.common import Page
from app.schemas.skill import (
    AgentSkillBindRequest,
    AgentSkillRead,
    SkillCreate,
    SkillExport,
    SkillRead,
    SkillUpdate,
)

router = APIRouter(prefix="/api/skills", tags=["skills"])
agent_router = APIRouter(prefix="/api/agents", tags=["skills"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[AppUser, Depends(get_current_user)]


async def _guard(awaitable):
    """把运行期 `SkillValidationError` 转为契约错误码 `SKILL_INVALID_PARAMS`。"""
    try:
        return await awaitable
    except SkillValidationError as exc:
        detail: dict[str, str] = {}
        if exc.skill_slug:
            detail["skill_slug"] = exc.skill_slug
        if exc.param:
            detail["param"] = exc.param
        raise AppError(
            exc.code,
            exc.message,
            http_status=400,
            detail=detail or None,
        ) from exc


# ----------------------------------------------------------------------
# Skill 广场（必须排在 /{skill_id} 之前）
# ----------------------------------------------------------------------


@router.get("/center", response_model=Page[SkillRead])
async def list_skill_center(
    session: SessionDep,
    user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    category: SkillCategory | None = None,
    keyword: str | None = None,
    sort: str = Query(default="latest", pattern="^(latest|popular)$"),
) -> Page[SkillRead]:
    items, total = await SkillRepository(session).list_center(
        owner_id=user.id,
        page=page,
        page_size=page_size,
        category=category.value if category else None,
        keyword=keyword,
        sort=sort,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


# ----------------------------------------------------------------------
# 我的 Skills
# ----------------------------------------------------------------------


@router.get("", response_model=Page[SkillRead])
async def list_my_skills(
    session: SessionDep,
    user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    visibility: SkillVisibility | None = None,
    status_filter: SkillStatus | None = Query(default=None, alias="status"),
    category: str | None = None,
    keyword: str | None = None,
) -> Page[SkillRead]:
    items, total = await SkillRepository(session).list_mine(
        owner_id=user.id,
        page=page,
        page_size=page_size,
        visibility=visibility,
        status=status_filter,
        category=category,
        keyword=keyword,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=SkillRead, status_code=status.HTTP_201_CREATED)
async def create_skill(
    payload: SkillCreate,
    session: SessionDep,
    user: CurrentUser,
) -> SkillRead:
    skill = await _guard(SkillRepository(session).create(owner_id=user.id, data=payload))
    await session.commit()
    return skill


@router.get("/{skill_id}", response_model=SkillRead)
async def get_skill(skill_id: int, session: SessionDep, user: CurrentUser) -> SkillRead:
    return await SkillRepository(session).get_visible(owner_id=user.id, skill_id=skill_id)


@router.put("/{skill_id}", response_model=SkillRead)
async def update_skill(
    skill_id: int,
    payload: SkillUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> SkillRead:
    skill = await _guard(
        SkillRepository(session).update(owner_id=user.id, skill_id=skill_id, data=payload)
    )
    await session.commit()
    return skill


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(skill_id: int, session: SessionDep, user: CurrentUser) -> Response:
    await SkillRepository(session).delete(owner_id=user.id, skill_id=skill_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{skill_id}/publish", response_model=SkillRead)
async def publish_skill(skill_id: int, session: SessionDep, user: CurrentUser) -> SkillRead:
    skill = await _guard(
        SkillRepository(session).publish(owner_id=user.id, skill_id=skill_id)
    )
    await session.commit()
    return skill


@router.post("/{skill_id}/archive", response_model=SkillRead)
async def archive_skill(skill_id: int, session: SessionDep, user: CurrentUser) -> SkillRead:
    skill = await SkillRepository(session).archive(owner_id=user.id, skill_id=skill_id)
    await session.commit()
    return skill


@router.post(
    "/{skill_id}/install",
    response_model=SkillRead,
    status_code=status.HTTP_201_CREATED,
)
async def install_skill(skill_id: int, session: SessionDep, user: CurrentUser) -> SkillRead:
    skill = await SkillRepository(session).install(user_id=user.id, skill_id=skill_id)
    await session.commit()
    return skill


@router.get("/{skill_id}/export", response_model=SkillExport)
async def export_skill(skill_id: int, session: SessionDep, user: CurrentUser) -> SkillExport:
    return await SkillRepository(session).export(owner_id=user.id, skill_id=skill_id)


# ----------------------------------------------------------------------
# Agent 挂载
# ----------------------------------------------------------------------


@agent_router.get("/{agent_id}/skills", response_model=list[AgentSkillRead])
async def list_agent_skills(
    agent_id: int, session: SessionDep, user: CurrentUser
) -> list[AgentSkillRead]:
    return await SkillRepository(session).agent_skills(agent_id=agent_id)


@agent_router.put("/{agent_id}/skills", response_model=list[AgentSkillRead])
async def replace_agent_skills(
    agent_id: int,
    payload: AgentSkillBindRequest,
    session: SessionDep,
    user: CurrentUser,
) -> list[AgentSkillRead]:
    skills = await _guard(
        SkillRepository(session).replace_agent_skills(
            agent_id=agent_id,
            owner_id=user.id,
            binds=payload.skills,
        )
    )
    await session.commit()
    return skills
