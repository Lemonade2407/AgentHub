"""MCP Server / Tool 仓储。数据库设计文档 §6.2、§6.3。归属：D（Platform Backend）。

同时实现 B 侧定义的 `ToolRegistry`、`ToolRegistryStore`、`McpServerStore`、
`McpServerProvider` 四个 Protocol，避免领域层直接依赖 ORM。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import McpServerStatus, RiskLevel, TransportType
from app.core.errors import AppError
from app.db.models import AgentTool, McpServer, McpTool, utcnow
from app.mcp.client_adapter import McpServerConfig
from app.mcp.discovery import NormalizedTool, ToolUpsertOutcome
from app.mcp.schemas import ToolDefinition
from app.schemas.mcp import McpServerCreate, McpServerRead, McpServerUpdate


class McpServerRepository:
    """`mcp_server` 读写 + `McpServerStore` / `McpServerProvider` 实现。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: McpServerCreate) -> McpServerRead:
        exists = (
            await self._session.execute(select(McpServer.id).where(McpServer.name == data.name))
        ).scalar_one_or_none()
        if exists is not None:
            raise AppError(
                "CONFLICT", f"MCP Server 名称已存在：{data.name}", http_status=409
            )

        server = McpServer(
            name=data.name,
            endpoint=data.endpoint,
            transport=data.transport.value,
            description=data.description,
            headers=data.headers,
            enabled=True,
            status=McpServerStatus.UNKNOWN.value,
        )
        self._session.add(server)
        await self._session.flush()
        return await self._to_read(server)

    async def get(self, server_id: int) -> McpServerRead:
        server = await self.get_raw(server_id)
        if server is None:
            raise AppError("NOT_FOUND", f"MCP Server 不存在：{server_id}", http_status=404)
        return await self._to_read(server)

    async def get_raw(self, server_id: int) -> McpServer | None:
        return (
            await self._session.execute(select(McpServer).where(McpServer.id == server_id))
        ).scalar_one_or_none()

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        status: McpServerStatus | None = None,
    ) -> tuple[list[McpServerRead], int]:
        conditions = []
        if status is not None:
            conditions.append(McpServer.status == status.value)

        total = int(
            (
                await self._session.execute(
                    select(func.count()).select_from(McpServer).where(*conditions)
                )
            ).scalar_one()
        )
        rows = (
            (
                await self._session.execute(
                    select(McpServer)
                    .where(*conditions)
                    .order_by(McpServer.created_at.desc(), McpServer.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return [await self._to_read(row) for row in rows], total

    async def update(
        self, server_id: int, data: McpServerUpdate
    ) -> tuple[McpServerRead, bool]:
        """返回 (DTO, 连接配置是否变化)。变化时调用方需丢弃缓存的 MCP Client。"""
        server = await self.get_raw(server_id)
        if server is None:
            raise AppError("NOT_FOUND", f"MCP Server 不存在：{server_id}", http_status=404)

        payload = data.model_dump(exclude_unset=True)
        changed_connection = False
        for field, value in payload.items():
            if value is None and field in {"endpoint", "transport"}:
                raise AppError(
                    "INVALID_ARGUMENT", f"字段 {field} 不能为 null", http_status=400
                )
            if field == "transport" and value is not None:
                value = TransportType(value).value
            if field in {"endpoint", "transport", "headers"} and getattr(server, field) != value:
                changed_connection = True
            setattr(server, field, value)

        if changed_connection:
            server.status = McpServerStatus.UNKNOWN.value
            server.last_error = None

        await self._session.flush()
        await self._session.refresh(server)
        return await self._to_read(server), changed_connection

    async def get_config(self, server_id: int) -> McpServerConfig | None:
        server = await self.get_raw(server_id)
        if server is None:
            return None
        return _to_config(server)

    async def update_status(
        self, *, server_id: int, status: McpServerStatus, last_error: str | None
    ) -> None:
        server = await self.get_raw(server_id)
        if server is None:
            return
        server.status = status.value
        server.last_error = last_error
        await self._session.flush()

    async def mark_discovered(self, *, server_id: int, discovered_at: datetime) -> None:
        server = await self.get_raw(server_id)
        if server is None:
            return
        server.last_discovered_at = discovered_at
        await self._session.flush()

    async def _to_read(self, server: McpServer) -> McpServerRead:
        tool_count = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(McpTool)
                    .where(McpTool.server_id == server.id)
                )
            ).scalar_one()
        )
        return McpServerRead(
            id=server.id,
            name=server.name,
            endpoint=server.endpoint,
            transport=TransportType(server.transport),
            description=server.description,
            enabled=server.enabled,
            status=McpServerStatus(server.status),
            last_error=server.last_error,
            last_discovered_at=server.last_discovered_at,
            tool_count=tool_count,
            created_at=server.created_at,
            updated_at=server.updated_at,
        )


class McpToolRepository:
    """`mcp_tool` 读写 + `ToolRegistry` / `ToolRegistryStore` 实现。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        server_id: int | None = None,
        enabled: bool | None = None,
        risk_level: RiskLevel | None = None,
        keyword: str | None = None,
    ) -> tuple[list[ToolDefinition], int]:
        conditions = []
        if server_id is not None:
            conditions.append(McpTool.server_id == server_id)
        if enabled is not None:
            conditions.append(McpTool.enabled.is_(enabled))
        if risk_level is not None:
            conditions.append(McpTool.risk_level == risk_level.value)
        if keyword:
            pattern = f"%{keyword}%"
            conditions.append(
                or_(McpTool.qualified_name.ilike(pattern), McpTool.description.ilike(pattern))
            )

        base = select(McpTool, McpServer.name).join(McpServer, McpServer.id == McpTool.server_id)
        count_stmt = (
            select(func.count())
            .select_from(McpTool)
            .join(McpServer, McpServer.id == McpTool.server_id)
            .where(*conditions)
        )
        total = int((await self._session.execute(count_stmt)).scalar_one())

        rows = (
            await self._session.execute(
                base.where(*conditions)
                .order_by(McpTool.server_id, McpTool.remote_name)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return [_to_definition(tool, server_name) for tool, server_name in rows], total

    async def get(self, tool_id: int) -> ToolDefinition | None:
        row = (
            await self._session.execute(
                select(McpTool, McpServer.name)
                .join(McpServer, McpServer.id == McpTool.server_id)
                .where(McpTool.id == tool_id)
            )
        ).first()
        if row is None:
            return None
        return _to_definition(row[0], row[1])

    async def get_by_qualified_name(self, qualified_name: str) -> ToolDefinition | None:
        row = (
            await self._session.execute(
                select(McpTool, McpServer.name)
                .join(McpServer, McpServer.id == McpTool.server_id)
                .where(McpTool.qualified_name == qualified_name)
            )
        ).first()
        if row is None:
            return None
        return _to_definition(row[0], row[1])

    async def list_bound_tools(self, *, agent_id: int) -> list[ToolDefinition]:
        rows = (
            await self._session.execute(
                select(McpTool, McpServer.name)
                .join(McpServer, McpServer.id == McpTool.server_id)
                .join(AgentTool, AgentTool.tool_id == McpTool.id)
                .where(AgentTool.agent_id == agent_id, McpTool.enabled.is_(True))
                .order_by(McpTool.id)
            )
        ).all()
        return [_to_definition(tool, server_name) for tool, server_name in rows]

    async def is_bound(self, *, agent_id: int, tool_id: int) -> bool:
        return (
            (
                await self._session.execute(
                    select(AgentTool.tool_id).where(
                        AgentTool.agent_id == agent_id, AgentTool.tool_id == tool_id
                    )
                )
            ).scalar_one_or_none()
            is not None
        )

    async def upsert_tool(self, tool: NormalizedTool) -> ToolUpsertOutcome:
        existing = (
            await self._session.execute(
                select(McpTool).where(
                    McpTool.server_id == tool.server_id,
                    McpTool.remote_name == tool.remote_name,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            self._session.add(
                McpTool(
                    server_id=tool.server_id,
                    remote_name=tool.remote_name,
                    qualified_name=tool.qualified_name,
                    description=tool.description,
                    input_schema=tool.input_schema,
                    risk_level=tool.risk_level.value,
                    enabled=tool.enabled,
                )
            )
            return ToolUpsertOutcome.ADDED

        existing.qualified_name = tool.qualified_name
        existing.description = tool.description
        existing.input_schema = tool.input_schema
        existing.risk_level = tool.risk_level.value
        existing.enabled = tool.enabled
        return ToolUpsertOutcome.UPDATED

    async def disable_tools_not_returned(
        self, *, server_id: int, remote_names: set[str]
    ) -> int:
        stmt = (
            update(McpTool)
            .where(McpTool.server_id == server_id)
            .values(enabled=False, updated_at=utcnow())
        )
        if remote_names:
            stmt = stmt.where(McpTool.remote_name.not_in(sorted(remote_names)))
        result = await self._session.execute(stmt)
        return int(result.rowcount or 0)

    async def count_tools(self, *, server_id: int) -> int:
        return int(
            (
                await self._session.execute(
                    select(func.count()).select_from(McpTool).where(McpTool.server_id == server_id)
                )
            ).scalar_one()
        )


class DbMcpServerProvider:
    """`McpServerProvider` 的数据库实现，供 Tool Router / Runtime 使用。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, server_id: int) -> McpServerConfig | None:
        server = (
            await self._session.execute(select(McpServer).where(McpServer.id == server_id))
        ).scalar_one_or_none()
        if server is None:
            return None
        return _to_config(server)


def _to_config(server: McpServer) -> McpServerConfig:
    return McpServerConfig(
        id=server.id,
        name=server.name,
        endpoint=server.endpoint,
        transport=TransportType(server.transport),
        headers=server.headers,
    )


def _to_definition(tool: McpTool, server_name: str) -> ToolDefinition:
    return ToolDefinition(
        id=tool.id,
        server_id=tool.server_id,
        server_name=server_name,
        remote_name=tool.remote_name,
        qualified_name=tool.qualified_name,
        description=tool.description,
        input_schema=tool.input_schema or {},
        risk_level=RiskLevel(tool.risk_level),
        enabled=tool.enabled,
        updated_at=tool.updated_at,
    )
