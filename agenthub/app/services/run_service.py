"""Run 编排服务：创建 Run、后台执行、回写终态。归属：D（Platform Backend）。"""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.model_provider import ModelConfigError, build_chat_model
from app.agent.runner import AgentRunner, RunResult
from app.core.enums import RunStatus, StepStatus, StopReason, TraceEventType
from app.core.errors import AppError
from app.mcp.client_adapter import HttpMcpClientFactory
from app.mcp.router import ToolRouter
from app.repositories.agent_repository import AgentRepository
from app.repositories.mcp_repository import DbMcpServerProvider, McpToolRepository
from app.repositories.run_repository import RunRepository
from app.schemas.agent import AgentRead
from app.schemas.run import RunCreateRequest, RunRead
from app.services.trace_service import SSEBroker, TraceService
from app.tools.selector import TfidfToolSelector
from app.trace.events import TraceEvent

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5


class RunService:
    """负责 Run 的创建与后台执行；Runtime 本身保持对 API 无感知。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        broker: SSEBroker,
        client_factory: HttpMcpClientFactory,
    ) -> None:
        self._session_factory = session_factory
        self._broker = broker
        self._client_factory = client_factory
        self._tasks: set[asyncio.Task] = set()

    async def create_run(
        self,
        session: AsyncSession,
        agent_id: int,
        request: RunCreateRequest,
    ) -> RunRead:
        agent = await AgentRepository(session).get(agent_id)
        if not agent.enabled:
            raise AppError("AGENT_DISABLED", f"Agent 已禁用：{agent_id}", http_status=409)

        tools = await McpToolRepository(session).list_bound_tools(agent_id=agent_id)
        if not tools:
            raise AppError(
                "NO_EXECUTABLE_TOOL",
                "Agent 至少需要绑定 1 个可用 Tool",
                http_status=422,
            )

        max_steps = request.max_steps or agent.max_steps
        run_id = f"r_{uuid4().hex[:20]}"
        thread_id = f"t_{uuid4().hex[:20]}"

        run = await RunRepository(session).create(
            run_id=run_id,
            agent_id=agent_id,
            thread_id=thread_id,
            user_input=request.input,
            max_steps=max_steps,
        )
        await session.commit()

        task = asyncio.create_task(
            self._execute(
                run_id=run_id,
                thread_id=thread_id,
                agent=agent,
                user_input=request.input,
                max_steps=max_steps,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return run

    async def _execute(
        self,
        *,
        run_id: str,
        thread_id: str,
        agent: AgentRead,
        user_input: str,
        max_steps: int,
    ) -> None:
        tracer = TraceService(self._session_factory, self._broker)

        async with self._session_factory() as session:
            gateway = ToolRouter(
                registry=McpToolRepository(session),
                servers=DbMcpServerProvider(session),
                client_factory=self._client_factory,
            )
            runner = AgentRunner(
                gateway=gateway,
                tool_selector=TfidfToolSelector(),
                model_factory=build_chat_model,
                top_k=DEFAULT_TOP_K,
            )
            try:
                result = await runner.run(
                    run_id=run_id,
                    thread_id=thread_id,
                    agent=agent,
                    user_input=user_input,
                    max_steps=max_steps,
                    tracer=tracer,
                )
            except ModelConfigError as exc:
                result = await self._fail_run(
                    run_id,
                    StopReason.MODEL_ERROR,
                    "LLM_AUTH_ERROR",
                    str(exc),
                    tracer,
                )
            except Exception as exc:  # 兜底：Run 必须有终态
                logger.exception("Run %s 执行时发生未归类异常", run_id)
                result = await self._fail_run(
                    run_id,
                    StopReason.INTERNAL_ERROR,
                    "INTERNAL_ERROR",
                    f"{type(exc).__name__}: {exc}"[:512],
                    tracer,
                )

            await RunRepository(session).finish(run_id, result)
            await session.commit()

    @staticmethod
    async def _fail_run(
        run_id: str,
        stop_reason: StopReason,
        error_code: str,
        error_message: str,
        tracer: TraceService,
    ) -> RunResult:
        await tracer.emit(
            TraceEvent(
                run_id=run_id,
                step_no=0,
                event_type=TraceEventType.RUN_FAILED,
                status=StepStatus.FAILED,
                data={
                    "stop_reason": stop_reason.value,
                    "error_code": error_code,
                    "error_message": error_message,
                },
            )
        )
        return RunResult(
            run_id=run_id,
            status=RunStatus.FAILED,
            stop_reason=stop_reason,
            output=None,
            llm_calls=0,
            tool_calls=0,
            step_count=0,
            duration_ms=0,
            error_code=error_code,
            error_message=error_message,
        )
