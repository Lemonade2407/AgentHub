"""API 依赖装配。归属：D（Platform Backend）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import get_session
from app.mcp.client_adapter import HttpMcpClientFactory
from app.models.user import AppUser
from app.services.run_service import RunService
from app.services.trace_service import SSEBroker

#: 内置 local 用户：local 模式（未登录演示）下所有资源的归属。
LOCAL_USER_EMAIL = "local@agenthub.local"


def get_run_service(request: Request) -> RunService:
    return request.app.state.run_service


def get_client_factory(request: Request) -> HttpMcpClientFactory:
    return request.app.state.client_factory


def get_broker(request: Request) -> SSEBroker:
    return request.app.state.broker


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    x_user_email: Annotated[str | None, Header(alias="X-User-Email")] = None,
) -> AppUser:
    """当前用户。

    `AUTH_MODE=local`（默认）时使用内置 local 用户；本地联调 / 验收可用
    `X-User-Email` 指定另一个账号，以便演示“公开后其他账号可见可安装”。
    账号体系落地后（`AUTH_MODE != local`）改为读取会话 Cookie。
    """
    settings = get_settings()
    if settings.auth_mode != "local":
        raise AppError("UNAUTHORIZED", "未登录或会话已失效", http_status=401)

    email = (x_user_email or LOCAL_USER_EMAIL).strip().lower()[:128]
    user = (
        await session.execute(select(AppUser).where(AppUser.email == email))
    ).scalar_one_or_none()
    if user is not None:
        return user

    display_name = "Local" if email == LOCAL_USER_EMAIL else email.split("@")[0][:64]
    user = AppUser(email=email, display_name=display_name, password_hash="!locked")
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        # 并发首次请求：另一个请求已创建，回滚后重新读取
        await session.rollback()
        return (
            await session.execute(select(AppUser).where(AppUser.email == email))
        ).scalar_one()
    await session.refresh(user)
    return user
