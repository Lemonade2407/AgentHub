"""统一错误模型与 FastAPI 异常处理器。契约 §1.4 / §1.5。归属：D（Platform Backend）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """业务异常：`code` 取契约 §1.5 的错误码。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 400,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.detail = detail


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or "req_unknown"


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def error_response(
    request: Request,
    *,
    code: str,
    message: str,
    http_status: int,
    detail: Any = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        content=jsonable_encoder(
            {
                "code": code,
                "message": message,
                "detail": detail,
                "request_id": _request_id(request),
                "timestamp": _timestamp(),
            }
        ),
    )


_STATUS_TO_CODE: dict[int, str] = {
    400: "INVALID_ARGUMENT",
    401: "LLM_AUTH_ERROR",
    403: "TOOL_NOT_BOUND",
    404: "NOT_FOUND",
    409: "CONFLICT",
    429: "LLM_QUOTA_EXCEEDED",
    500: "INTERNAL_ERROR",
    501: "NOT_IMPLEMENTED",
    502: "MCP_SERVER_UNREACHABLE",
    503: "DB_UNAVAILABLE",
    504: "TOOL_TIMEOUT",
}


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return error_response(
        request,
        code=exc.code,
        message=exc.message,
        http_status=exc.http_status,
        detail=exc.detail,
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return error_response(
        request,
        code="VALIDATION_ERROR",
        message="请求参数不合法",
        http_status=400,
        detail=exc.errors(),
    )


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    detail = exc.detail
    message = detail if isinstance(detail, str) else "请求失败"
    code = _STATUS_TO_CODE.get(exc.status_code, "INTERNAL_ERROR")
    return error_response(
        request,
        code=code,
        message=message,
        http_status=exc.status_code,
        detail=None if isinstance(detail, str) else detail,
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未归类异常：%s %s", request.method, request.url.path)
    return error_response(
        request,
        code="INTERNAL_ERROR",
        message="服务内部错误",
        http_status=500,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
