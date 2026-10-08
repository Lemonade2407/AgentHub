"""Discovery 与风险推断单测（契约 §3.2、§3.3、§4.2.6 / D9）。"""

from __future__ import annotations

import pytest

from app.core.enums import McpServerStatus, RiskLevel
from app.mcp.client_adapter import MCP_SERVER_UNREACHABLE, McpClientError
from app.mcp.discovery import (
    MCP_DISCOVERY_FAILED,
    DiscoveryService,
    McpDiscoveryError,
    infer_risk_level,
    server_slug,
)
from app.mcp.discovery import NormalizedTool
from tests.mcp_fakes import (
    FakeMcpClient,
    FakeMcpClientFactory,
    InMemoryToolRegistryStore,
    RecordingServerStore,
    make_server,
    make_tool_info,
)


def make_service(client: FakeMcpClient, *, store=None, server_store=None):
    store = store if store is not None else InMemoryToolRegistryStore()
    server_store = server_store if server_store is not None else RecordingServerStore()
    service = DiscoveryService(
        registry_store=store,
        server_store=server_store,
        client_factory=FakeMcpClientFactory(client),
    )
    return service, store, server_store


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("GitHub MCP", "github_mcp"),
        ("demo", "demo"),
        ("My--Server!", "my_server"),
        ("  A  B  ", "a_b"),
        ("!!!", ""),
    ],
)
def test_server_slug(name: str, expected: str) -> None:
    assert server_slug(name) == expected


@pytest.mark.parametrize(
    ("remote_name", "read_only_hint", "expected"),
    [
        ("delete_all", True, RiskLevel.READ_ONLY),  # 规则 1 优先
        ("get_issue", None, RiskLevel.READ_ONLY),
        ("list_repos", None, RiskLevel.READ_ONLY),
        ("create_issue", None, RiskLevel.WRITE),
        ("delete_repo", None, RiskLevel.WRITE),
        ("run_shell", None, RiskLevel.HIGH_RISK),
        ("do_exec", None, RiskLevel.HIGH_RISK),
        ("transfer_funds", None, RiskLevel.HIGH_RISK),
        ("echo", None, RiskLevel.LOW_RISK),
    ],
)
def test_infer_risk_level(remote_name: str, read_only_hint: bool | None, expected: RiskLevel) -> None:
    assert infer_risk_level(remote_name, read_only_hint=read_only_hint) is expected


async def test_discover_upserts_and_applies_boundary_rules() -> None:
    client = FakeMcpClient(
        tools=[
            make_tool_info("list_issues"),
            make_tool_info("create_issue"),
            make_tool_info("run_shell"),  # HIGH_RISK -> 丢弃
            make_tool_info("update_note", input_schema={"type": "array"}),  # 非法 schema
            make_tool_info("t" * 129),  # 超长 -> 跳过
        ]
    )
    service, store, server_store = make_service(client)

    result = await service.discover(make_server())

    assert result.status is McpServerStatus.CONNECTED
    assert (result.added, result.updated, result.removed, result.total) == (3, 0, 0, 3)

    list_issues = store.tools[(1, "list_issues")]
    assert list_issues.qualified_name == "github.list_issues"
    assert list_issues.risk_level is RiskLevel.READ_ONLY
    assert list_issues.enabled is True

    # 非法 schema：以 {} 入库并置 enabled=false
    update_note = store.tools[(1, "update_note")]
    assert update_note.input_schema == {}
    assert update_note.enabled is False
    assert update_note.risk_level is RiskLevel.WRITE

    assert (1, "run_shell") not in store.tools
    assert all(name != "t" * 129 for _, name in store.tools)

    assert server_store.status_updates[-1] == (1, McpServerStatus.CONNECTED, None)
    assert len(server_store.discoveries) == 1


async def test_discover_disables_tools_not_returned() -> None:
    existing = NormalizedTool(
        server_id=1,
        remote_name="old_tool",
        qualified_name="github.old_tool",
        risk_level=RiskLevel.LOW_RISK,
    )
    store = InMemoryToolRegistryStore([existing])
    client = FakeMcpClient(tools=[make_tool_info("list_issues")])
    service, _, _ = make_service(client, store=store)

    result = await service.discover(make_server())

    assert (result.added, result.updated, result.removed, result.total) == (1, 0, 1, 2)
    assert store.tools[(1, "old_tool")].enabled is False


async def test_discover_failure_marks_error_and_raises() -> None:
    client = FakeMcpClient(list_error=McpClientError(MCP_SERVER_UNREACHABLE, "connection refused"))
    service, _, server_store = make_service(client)

    with pytest.raises(McpDiscoveryError) as excinfo:
        await service.discover(make_server())

    assert excinfo.value.error_code == MCP_DISCOVERY_FAILED
    assert server_store.status_updates[-1] == (1, McpServerStatus.ERROR, "connection refused")


async def test_test_connection_success() -> None:
    client = FakeMcpClient(server_info={"name": "demo", "version": "1.0"})
    service, _, server_store = make_service(client)

    result = await service.test_connection(make_server())

    assert result.ok is True
    assert result.status is McpServerStatus.CONNECTED
    assert result.server_info == {"name": "demo", "version": "1.0"}
    assert result.error_code is None
    assert server_store.status_updates[-1] == (1, McpServerStatus.CONNECTED, None)
    # 连通性测试不算 Discovery
    assert server_store.discoveries == []


async def test_test_connection_failure() -> None:
    client = FakeMcpClient(init_error=McpClientError(MCP_SERVER_UNREACHABLE, "connection refused"))
    service, _, server_store = make_service(client)

    result = await service.test_connection(make_server())

    assert result.ok is False
    assert result.status is McpServerStatus.ERROR
    assert result.error_code == MCP_SERVER_UNREACHABLE
    assert server_store.status_updates[-1] == (1, McpServerStatus.ERROR, "connection refused")
