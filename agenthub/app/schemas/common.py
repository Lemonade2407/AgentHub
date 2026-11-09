<<<<<<< HEAD
"""公共 DTO（契约 §1.3 分页、§1.4 错误响应）。"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict
=======
"""分页通用 DTO。契约 §1.3。归属：D（Platform Backend）。"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel
>>>>>>> 47840490efc0088f6d22732094d9c57c7571fb6e

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
<<<<<<< HEAD
    """契约 §1.3 —— 统一分页响应。

    需继承 `Generic[T]` 才允许 `Page[AgentRead]` 形式的参数化。
    """

=======
>>>>>>> 47840490efc0088f6d22732094d9c57c7571fb6e
    items: list[T]
    total: int
    page: int
    page_size: int
<<<<<<< HEAD


class ErrorResponse(BaseModel):
    """契约 §1.4 —— 统一错误响应（同步接口）。"""

    code: str
    message: str
    detail: dict | None = None
    request_id: str
    timestamp: datetime
=======
>>>>>>> 47840490efc0088f6d22732094d9c57c7571fb6e
