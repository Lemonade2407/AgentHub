"""契约 §6.1 / §7.3 冻结接口：A 调用、B 实现。归属：B（Tool Selection）。

V1 实现建议：`TfidfToolSelector`（TF-IDF + cosine，Top-K 默认 5）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from app.mcp.schemas import ToolDefinition


class ToolCandidate(BaseModel):
    """一个候选工具及其相关性得分（契约 §6.1）。"""

    tool: ToolDefinition
    score: float


@runtime_checkable
class ToolSelector(Protocol):
    """动态工具选择器（设计文档 §7）。"""

    async def select(
        self,
        query: str,
        tools: list[ToolDefinition],
        top_k: int = 5,
    ) -> list[ToolCandidate]:
        """从 `tools` 中筛选与 `query` 最相关的 Top-K 候选。

        约定：只做筛选与排序，不改变 Tool 本身；返回数量不超过 `top_k`，按 `score` 降序。
        """
