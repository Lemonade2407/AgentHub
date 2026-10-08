"""Permission Guard 单测（契约 §2.4、§10 D2）。"""

from __future__ import annotations

import pytest

from app.core.enums import RiskLevel
from app.tools.permission import PermissionGuard, ToolPermissionDenied
from tests.mcp_fakes import make_tool

GUARD = PermissionGuard()


def test_read_only_is_allowed() -> None:
    GUARD.check(agent_id=1, tool=make_tool("github.list_issues", risk_level=RiskLevel.READ_ONLY))


def test_low_risk_enabled_is_allowed() -> None:
    GUARD.check(agent_id=1, tool=make_tool("note.echo", risk_level=RiskLevel.LOW_RISK, enabled=True))


@pytest.mark.parametrize("risk_level", [RiskLevel.WRITE, RiskLevel.HIGH_RISK])
def test_write_and_high_risk_are_denied(risk_level: RiskLevel) -> None:
    with pytest.raises(ToolPermissionDenied) as excinfo:
        GUARD.check(agent_id=1, tool=make_tool("repo.delete_all", risk_level=risk_level))

    assert excinfo.value.error_code == "TOOL_RISK_DENIED"


def test_disabled_tool_is_denied() -> None:
    with pytest.raises(ToolPermissionDenied) as excinfo:
        GUARD.check(agent_id=1, tool=make_tool("github.list_issues", enabled=False))

    assert excinfo.value.error_code == "TOOL_RISK_DENIED"
