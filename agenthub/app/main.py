"""FastAPI 应用装配入口（注册路由 + 统一错误处理器）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.errors import AgentHubHTTPException
from app.api.routers import agent, mcp
from app.schemas.common import ErrorResponse

app = FastAPI(title="AgentHub API", version="0.1.0")


# ---------- 路由注册 ----------

app.include_router(agent.router)
app.include_router(mcp.router)


# ---------- 根路径保留 ----------


@app.get("/", tags=["meta"])
def read_root() -> dict:
    return {"message": "AgentHub 后端服务已成功启动！"}


# ---------- 统一错误响应 ----------


@app.exception_handler(AgentHubHTTPException)
async def agenthub_exception_handler(
    request: Request, exc: AgentHubHTTPException
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(
            code=exc.code,
            message=exc.message,
            request_id=_resolve_request_id(request),
            detail=exc.detail,
        ),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_error_payload(
            code="VALIDATION_ERROR",
            message="request body validation failed",
            request_id=_resolve_request_id(request),
            detail={"errors": exc.errors()},
        ),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_payload(
            code="INTERNAL_ERROR",
            message="unexpected server error",
            request_id=_resolve_request_id(request),
        ),
    )


def _error_payload(
    code: str, message: str, request_id: str, detail: dict | None = None
) -> dict:
    """用显式 ISO 串避免 JSONResponse 直 dump datetime 报 TypeError。

    参数顺序刻意把 `detail` 放最后并给默认值，让 unhandled_exception_handler
    这种场景（不带 detail）也能正常调用，不再抛 TypeError。
    """
    return {
        "code": code,
        "message": message,
        "detail": detail,
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _resolve_request_id(request: Request) -> str:
    return request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex[:12]}"
