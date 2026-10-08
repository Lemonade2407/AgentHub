"""AgentHub Demo MCP Server（B 的 MCP 集成测试对端，契约 §9.1）。

启动：`python -m demo_mcp_server --host 0.0.0.0 --port 8100`
"""

from demo_mcp_server.server import TOOLS, build_server, dispatch, list_tool_schemas

__all__ = ["TOOLS", "build_server", "dispatch", "list_tool_schemas"]
