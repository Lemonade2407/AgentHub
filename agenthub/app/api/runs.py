"""Run 与 Trace 路由。契约 §4.3 / §4.4 / §4.5。归属：D（Platform Backend）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_broker, get_run_service
from app.core.enums import RunStatus, StopReason, TraceEventType
from app.core.errors import AppError
from app.db.session import SessionFactory, get_session
from app.repositories.run_repository import RunRepository
from app.repositories.trace_repository import TraceRepository
from app.schemas.common import Page
from app.schemas.run import RunCreateRequest, RunRead, StepRead
from app.services.run_service import RunService
from app.services.trace_service import SSEBroker, TERMINAL_EVENTS
from app.trace.events import TraceEvent

router = APIRouter(prefix="/api", tags=["runs"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.post("/agents/{agent_id}/runs", response_model=RunRead, status_code=202)
async def create_run(
    agent_id: int,
    payload: RunCreateRequest,
    session: AsyncSession = Depends(get_session),
    run_service: RunService = Depends(get_run_service),
) -> RunRead:
    return await run_service.create_run(session, agent_id, payload)


@router.get("/agents/{agent_id}/runs", response_model=Page[RunRead])
async def list_agent_runs(
    agent_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: RunStatus | None = None,
    sort: str = "-created_at",
    session: AsyncSession = Depends(get_session),
) -> Page[RunRead]:
    items, total = await RunRepository(session).list_by_agent(
        agent_id=agent_id,
        page=page,
        page_size=page_size,
        status=status,
        sort=sort,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/runs/{run_id}", response_model=RunRead)
async def get_run(
    run_id: str,
    session: AsyncSession = Depends(get_session),
) -> RunRead:
    return await RunRepository(session).get(run_id)


@router.get("/runs/{run_id}/steps", response_model=Page[StepRead])
async def list_run_steps(
    run_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500),
    after_step_no: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> Page[StepRead]:
    await RunRepository(session).get(run_id)  # 404 校验
    items, total = await TraceRepository(session).list_steps(
        run_id=run_id,
        page=page,
        page_size=page_size,
        after_step_no=after_step_no,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, session: AsyncSession = Depends(get_session)):
    await RunRepository(session).get(run_id)  # 404 校验
    raise AppError(
        "NOT_IMPLEMENTED",
        "取消 Run 在 V1 未实现（P2）",
        http_status=501,
    )


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    request: Request,
    broker: SSEBroker = Depends(get_broker),
) -> StreamingResponse:
    async with SessionFactory() as session:
        await RunRepository(session).get(run_id)  # 404 校验

    raw_last_id = request.headers.get("Last-Event-ID")
    try:
        last_event_id = max(int(raw_last_id or 0), 0)
    except ValueError:
        last_event_id = 0

    async def event_stream() -> AsyncIterator[str]:
        last_id = last_event_id

        # 先订阅再查历史：避免两者之间产生的事件丢失；重复事件按 id 去重
        async with broker.subscribe(run_id) as queue:
            async with SessionFactory() as session:
                history = await TraceRepository(session).list_all_after(
                    run_id=run_id, after_id=last_id
                )
                run = await RunRepository(session).get(run_id)

            for step in history:
                last_id = max(last_id, step.id)
                yield _sse_frame(_step_to_event(step))

            if run.status in {
                RunStatus.SUCCESS,
                RunStatus.PARTIAL,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
            }:
                return

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue

                if event.id is not None:
                    if event.id <= last_id:
                        continue
                    last_id = event.id

                yield _sse_frame(event)
                if event.event_type.value in TERMINAL_EVENTS:
                    return

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS
    )


def _step_to_event(step: StepRead) -> TraceEvent:
    return TraceEvent(
        id=step.id,
        run_id=step.run_id,
        step_no=step.step_no,
        event_type=step.event_type,
        status=step.status,
        node=step.node,
        tool=step.tool,
        duration_ms=step.duration_ms,
        data=step.payload,
        timestamp=step.created_at,
    )


def _sse_frame(event: TraceEvent) -> str:
    """契约 §5.1：`event` = 小写事件名，`id` = agent_step.id（Last-Event-ID 依据）。"""
    payload = json.dumps(
        event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
    )
    lines = [f"event: {event.event_type.value.lower()}"]
    if event.id is not None:
        lines.append(f"id: {event.id}")
    lines.append(f"data: {payload}")
    return "\n".join(lines) + "\n\n"
