"""Agent CRUD + Run 路由（契约 §4.1、§4.3）。

CRUD 接口规则：
- 创建：201 + AgentRead；tool_ids 必须存在，否则 TOOL_NOT_FOUND。
- 列表：Page[AgentRead]，带 enabled / keyword 过滤。
- 详情：GET；不存在 → 404。
- 更新：PUT 部分覆盖（未传字段保留原值）。
- 删除：DELETE → 204；V1 软删除（deleted_at IS NULL 默认过滤）。
- 绑定工具：PUT /{id}/tools 全量覆盖。

Run 接口：
- POST /{agent_id}/runs → 落库 AgentRun（status=PENDING），返回 RunRead，202 Accepted；
  V1 尚未接 LangGraph runner，Runner 接入后把本函数的 stub 返回替换为真正执行。
- GET  /{agent_id}/runs → 历史 Run 列表分页。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AgentHubHTTPException, conflict, not_found
from app.core.db import get_session
from app.core.enums import RunStatus
from app.models.agent import Agent, AgentTool
from app.models.mcp import McpTool
from app.models.run import AgentRun
from app.schemas.agent import (
    AgentCreate,
    AgentRead,
    AgentToolBind,
    AgentUpdate,
    RunCreateRequest,
    RunRead,
)
from app.schemas.common import Page

router = APIRouter(prefix="/api/agents", tags=["agents"])


# ---------- helpers ----------


async def _agent_or_404(session: AsyncSession, agent_id: int) -> Agent:
    agent = (
        await session.execute(
            select(Agent).where(Agent.id == agent_id, Agent.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if agent is None:
        raise not_found(f"Agent {agent_id} not found")
    return agent


async def _fetch_tool_ids(session: AsyncSession, agent_id: int) -> list[int]:
    rows = (
        await session.execute(
            select(AgentTool.tool_id).where(AgentTool.agent_id == agent_id)
        )
    ).all()
    return sorted(r[0] for r in rows)


def _build_agent_read(agent: Agent, tool_ids: list[int]) -> AgentRead:
    return AgentRead(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        model=agent.model,
        system_prompt=agent.system_prompt,
        max_steps=agent.max_steps,
        enabled=agent.enabled,
        tool_ids=tool_ids,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


async def _ensure_tools_exist(session: AsyncSession, tool_ids: list[int]) -> None:
    if not tool_ids:
        return
    rows = (
        await session.execute(
            select(func.count(McpTool.id)).where(McpTool.id.in_(tool_ids))
        )
    ).scalar_one()
    if rows != len(tool_ids):
        raise AgentHubHTTPException(
            status.HTTP_404_NOT_FOUND,
            "TOOL_NOT_FOUND",
            "some tool_ids do not exist",
            detail={"tool_ids": tool_ids},
        )


async def _unique_name_conflict_handler(session: AsyncSession) -> None:
    """捕获 IntegrityError 中 agent.name 唯一冲突。"""
    await session.rollback()
    raise conflict("agent name already exists")


# ---------- 4.1.1 创建 ----------


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentRead:
    await _ensure_tools_exist(session, payload.tool_ids)

    agent = Agent(
        name=payload.name,
        description=payload.description,
        model=payload.model,
        system_prompt=payload.system_prompt,
        max_steps=payload.max_steps,
        enabled=payload.enabled,
    )
    session.add(agent)
    await session.flush()

    if payload.tool_ids:
        session.add_all([AgentTool(agent_id=agent.id, tool_id=tid) for tid in payload.tool_ids])

    try:
        await session.commit()
    except IntegrityError:
        await _unique_name_conflict_handler(session)

    await session.refresh(agent)
    return _build_agent_read(agent, sorted(payload.tool_ids))


# ---------- 4.1.2 列表 ----------


@router.get("", response_model=Page[AgentRead])
async def list_agents(
    session: Annotated[AsyncSession, Depends(get_session)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    enabled: bool | None = None,
    keyword: str | None = None,
) -> Page[AgentRead]:
    conditions = [Agent.deleted_at.is_(None)]
    if enabled is not None:
        conditions.append(Agent.enabled == enabled)
    if keyword:
        conditions.append(Agent.name.ilike(f"%{keyword}%"))

    stmt = select(Agent).where(*conditions)
    total = (
        await session.execute(select(func.count(Agent.id)).where(*conditions))
    ).scalar_one()

    offset = (page - 1) * page_size
    agents = (
        (await session.execute(stmt.order_by(Agent.created_at.desc()).offset(offset).limit(page_size)))
        .scalars()
        .all()
    )

    ids = [a.id for a in agents]
    tool_rows = (
        await session.execute(
            select(AgentTool.agent_id, AgentTool.tool_id).where(AgentTool.agent_id.in_(ids))
        )
    ).all()
    tool_map: dict[int, list[int]] = {aid: [] for aid in ids}
    for aid, tid in tool_rows:
        tool_map[aid].append(tid)

    items = [_build_agent_read(a, sorted(tool_map[a.id])) for a in agents]
    return Page(items=items, total=total, page=page, page_size=page_size)


# ---------- 4.1.3 详情 ----------


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(
    agent_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentRead:
    agent = await _agent_or_404(session, agent_id)
    return _build_agent_read(agent, await _fetch_tool_ids(session, agent_id))


# ---------- 4.1.4 修改 ----------


@router.put("/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: int,
    payload: AgentUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentRead:
    agent = await _agent_or_404(session, agent_id)

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        return _build_agent_read(agent, await _fetch_tool_ids(session, agent_id))

    for k, v in update_data.items():
        setattr(agent, k, v)

    try:
        await session.commit()
    except IntegrityError:
        await _unique_name_conflict_handler(session)

    await session.refresh(agent)
    return _build_agent_read(agent, await _fetch_tool_ids(session, agent_id))


# ---------- 4.1.5 删除（软删除） ----------


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    agent = await _agent_or_404(session, agent_id)
    agent.deleted_at = datetime.utcnow()
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- 4.1.6 更新工具绑定 ----------


@router.put("/{agent_id}/tools", response_model=AgentRead)
async def bind_tools(
    agent_id: int,
    payload: AgentToolBind,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentRead:
    agent = await _agent_or_404(session, agent_id)
    await _ensure_tools_exist(session, payload.tool_ids)

    await session.execute(delete(AgentTool).where(AgentTool.agent_id == agent_id))

    if payload.tool_ids:
        session.add_all([AgentTool(agent_id=agent_id, tool_id=tid) for tid in payload.tool_ids])

    await session.commit()
    return _build_agent_read(agent, sorted(payload.tool_ids))


# ---------- 4.3 Run 接口 ----------


def _new_run_id() -> str:
    """契约 §0.3：`r_` + 12 位小写十六进制。"""

    return f"r_{uuid.uuid4().hex[:12]}"


def _new_thread_id() -> str:
    """契约 §0.3：V1 每次 Run 新建 thread_id，不复用。"""

    return f"t_{uuid.uuid4().hex[:12]}"


def _build_run_read(run: AgentRun) -> RunRead:
    return RunRead(
        id=run.id,
        agent_id=run.agent_id,
        thread_id=run.thread_id,
        status=run.status,
        stop_reason=run.stop_reason,
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


@router.post("/{agent_id}/runs", response_model=RunRead, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    agent_id: int,
    payload: RunCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunRead:
    agent = await _agent_or_404(session, agent_id)
    if not agent.enabled:
        raise AgentHubHTTPException(
            status.HTTP_409_CONFLICT,
            "AGENT_DISABLED",
            f"agent {agent_id} is disabled, cannot start run",
        )

    max_steps = payload.max_steps if payload.max_steps is not None else agent.max_steps

    run = AgentRun(
        id=_new_run_id(),
        agent_id=agent.id,
        thread_id=_new_thread_id(),
        status=RunStatus.PENDING.value,
        input=payload.input,
        max_steps=max_steps,
        llm_calls=0,
        tool_calls=0,
        step_count=0,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    # V1 stub：LangGraph runner 接入后在这里异步触发实际执行。
    # 保持同步返回 PENDING 的 RunRead，不阻塞 HTTP 响应。
    return _build_run_read(run)


@router.get("/{agent_id}/runs", response_model=Page[RunRead])
async def list_runs(
    agent_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_: str | None = Query(default=None, alias="status"),
) -> Page[RunRead]:
    await _agent_or_404(session, agent_id)

    conditions = [AgentRun.agent_id == agent_id]
    if status_ is not None:
        conditions.append(AgentRun.status == status_)

    from sqlalchemy import and_

    where_clause = and_(*conditions) if len(conditions) > 1 else conditions[0]

    total = (
        await session.execute(
            select(func.count(AgentRun.id)).where(where_clause)
        )
    ).scalar_one()

    offset = (page - 1) * page_size
    runs = (
        (await session.execute(
            select(AgentRun)
            .where(where_clause)
            .order_by(AgentRun.created_at.desc())
            .offset(offset)
            .limit(page_size)
        ))
        .scalars()
        .all()
    )

    return Page(
        items=[_build_run_read(r) for r in runs],
        total=total,
        page=page,
        page_size=page_size,
    )
