"""Agent 路由。契约 §4.1。归属：D（Platform Backend）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.repositories.agent_repository import AgentRepository
from app.schemas.agent import AgentCreate, AgentRead, AgentToolBind, AgentUpdate
from app.schemas.common import Page

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.post("", response_model=AgentRead, status_code=201)
async def create_agent(
    payload: AgentCreate,
    session: AsyncSession = Depends(get_session),
) -> AgentRead:
    agent = await AgentRepository(session).create(payload)
    await session.commit()
    return agent


@router.get("", response_model=Page[AgentRead])
async def list_agents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    enabled: bool | None = None,
    keyword: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> Page[AgentRead]:
    items, total = await AgentRepository(session).list(
        page=page, page_size=page_size, enabled=enabled, keyword=keyword
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(
    agent_id: int,
    session: AsyncSession = Depends(get_session),
) -> AgentRead:
    return await AgentRepository(session).get(agent_id)


@router.put("/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: int,
    payload: AgentUpdate,
    session: AsyncSession = Depends(get_session),
) -> AgentRead:
    agent = await AgentRepository(session).update(agent_id, payload)
    await session.commit()
    return agent


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await AgentRepository(session).soft_delete(agent_id)
    await session.commit()
    return Response(status_code=204)


@router.put("/{agent_id}/tools", response_model=AgentRead)
async def bind_agent_tools(
    agent_id: int,
    payload: AgentToolBind,
    session: AsyncSession = Depends(get_session),
) -> AgentRead:
    agent = await AgentRepository(session).bind_tools(agent_id, payload.tool_ids)
    await session.commit()
    return agent
