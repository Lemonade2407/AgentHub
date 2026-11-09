"""StopPolicy 单元测试（设计文档 §6.4 / 契约 §2.2）。"""

from __future__ import annotations

import pytest

from app.agent.stop_policy import StopPolicy
from app.core.enums import RunStatus, StopReason


def test_max_steps_must_be_positive() -> None:
    with pytest.raises(ValueError):
        StopPolicy(0)


@pytest.mark.parametrize(
    ("step_count", "expected"),
    [(0, False), (7, False), (8, True), (9, True)],
)
def test_budget_exhausted(step_count: int, expected: bool) -> None:
    assert StopPolicy(8).budget_exhausted(step_count) is expected


@pytest.mark.parametrize(
    ("stop_reason", "final_answer", "expected"),
    [
        (StopReason.FINISHED, "answer", RunStatus.SUCCESS),
        (StopReason.MAX_STEPS, "partial", RunStatus.PARTIAL),
        (StopReason.MAX_STEPS, None, RunStatus.FAILED),
        (StopReason.MODEL_ERROR, None, RunStatus.FAILED),
        (StopReason.MODEL_ERROR, "partial", RunStatus.FAILED),
        (StopReason.TOOL_ERROR, None, RunStatus.FAILED),
        (StopReason.CANCELLED, None, RunStatus.CANCELLED),
    ],
)
def test_resolve_status(
    stop_reason: StopReason,
    final_answer: str | None,
    expected: RunStatus,
) -> None:
    status = StopPolicy(8).resolve_status(stop_reason=stop_reason, final_answer=final_answer)
    assert status is expected
