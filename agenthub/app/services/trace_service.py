"""Trace Service 与 SSE 广播。设计文档 §9 / 契约 §5、§6.3。归属：D（Trace Service）。"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.repositories.trace_repository import TraceRepository
from app.trace.events import TraceEvent

logger = logging.getLogger(__name__)

TERMINAL_EVENTS = {"RUN_FINISHED", "RUN_FAILED"}


class SSEBroker:
    """单实例进程内广播。

    契约明确 V1 不引入 Redis / 消息队列，SSE 仅支持单 backend 实例（设计文档 §14）。
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[TraceEvent]]] = {}

    @asynccontextmanager
    async def subscribe(self, run_id: str) -> AsyncIterator[asyncio.Queue[TraceEvent]]:
        queue: asyncio.Queue[TraceEvent] = asyncio.Queue()
        self._subscribers.setdefault(run_id, set()).add(queue)
        try:
            yield queue
        finally:
            subscribers = self._subscribers.get(run_id)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    self._subscribers.pop(run_id, None)

    async def publish(self, event: TraceEvent) -> None:
        for queue in list(self._subscribers.get(event.run_id, ())):
            queue.put_nowait(event)


class TraceService:
    """`TraceSink` 实现：先持久化，再广播。

    契约 §6.3：**不抛异常**；DB 写失败只记日志，不阻断 Runtime。
    Trace 使用独立短事务，避免长事务拖住 Run。
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        broker: SSEBroker,
    ) -> None:
        self._session_factory = session_factory
        self._broker = broker

    async def emit(self, event: TraceEvent) -> None:
        try:
            async with self._session_factory() as session:
                step_id = await TraceRepository(session).insert(event)
                await session.commit()
            event.id = step_id
        except Exception:
            logger.exception(
                "Trace 持久化失败（run=%s, event=%s），降级为仅推送",
                event.run_id,
                event.event_type.value,
            )

        try:
            await self._broker.publish(event)
        except Exception:
            logger.exception("Trace 广播失败（run=%s）", event.run_id)
