"""停止策略。设计文档 §6.4 / 契约 §2.2。归属：A（Agent Runtime）。

本模块只做纯判定，不依赖 LangGraph，便于单元测试。
"""

from __future__ import annotations

from app.core.enums import RunStatus, StopReason


class StopPolicy:
    """把「Run 为何结束」映射为 `RunStatus`，并判定步数预算。"""

    def __init__(self, max_steps: int) -> None:
        if max_steps < 1:
            raise ValueError("max_steps 必须 >= 1")
        self.max_steps = max_steps

    def budget_exhausted(self, step_count: int) -> bool:
        """契约 §2.2：`step_count >= max_steps` 触发 MAX_STEPS。

        判定的是图执行步数，因此一次 Run 的节点执行次数不会超过 `max_steps`。
        """
        return step_count >= self.max_steps

    def resolve_status(
        self,
        *,
        stop_reason: StopReason,
        final_answer: str | None,
    ) -> RunStatus:
        """契约 §2.2 的 `StopReason -> RunStatus` 映射。

        MAX_STEPS 的结果取决于是否已经产出答案：有则为 PARTIAL，无则为 FAILED。
        """
        match stop_reason:
            case StopReason.FINISHED:
                return RunStatus.SUCCESS
            case StopReason.MAX_STEPS:
                return RunStatus.PARTIAL if final_answer else RunStatus.FAILED
            case StopReason.CANCELLED:
                return RunStatus.CANCELLED
            case _:
                # MODEL_ERROR / TOOL_ERROR
                return RunStatus.FAILED
