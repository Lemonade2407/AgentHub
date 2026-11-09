"""契约 §1.4 —— 统一异常，把 HTTPException 转成 ErrorResponse。"""

from __future__ import annotations

from fastapi import HTTPException, status


class AgentHubHTTPException(HTTPException):
    """携带业务 `code` 的 HTTPException；由 app/main.py 的异常处理器消费。"""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        detail: dict | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message
        self.detail = detail


# 便捷构造器
def not_found(message: str, detail: dict | None = None) -> AgentHubHTTPException:
    return AgentHubHTTPException(status.HTTP_404_NOT_FOUND, "NOT_FOUND", message, detail)


def conflict(message: str, detail: dict | None = None) -> AgentHubHTTPException:
    return AgentHubHTTPException(status.HTTP_409_CONFLICT, "CONFLICT", message, detail)


def invalid_argument(message: str, detail: dict | None = None) -> AgentHubHTTPException:
    return AgentHubHTTPException(status.HTTP_400_BAD_REQUEST, "INVALID_ARGUMENT", message, detail)


def forbidden(code: str, message: str, detail: dict | None = None) -> AgentHubHTTPException:
    return AgentHubHTTPException(status.HTTP_403_FORBIDDEN, code, message, detail)
