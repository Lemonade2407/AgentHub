"""API 依赖装配。归属：D（Platform Backend）。"""

from __future__ import annotations

from fastapi import Request

from app.mcp.client_adapter import HttpMcpClientFactory
from app.services.run_service import RunService
from app.services.trace_service import SSEBroker


def get_run_service(request: Request) -> RunService:
    return request.app.state.run_service


def get_client_factory(request: Request) -> HttpMcpClientFactory:
    return request.app.state.client_factory


def get_broker(request: Request) -> SSEBroker:
    return request.app.state.broker
