"""契约 §6.1 / §7.3 冻结接口：A 调用、B 实现。归属：B（Tool Selection）。

V1 实现：`TfidfToolSelector`（TF-IDF + cosine，Top-K 默认 5，设计文档 §7.2）。
只依赖标准库，不引入 numpy / scikit-learn —— V1 的 Tool 数量为几十级（设计文档 §7.4）。
"""

from __future__ import annotations

import math
import re
from collections import Counter
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


# 驼峰边界：`listIssues` -> `list Issues`
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
# 词元：ASCII 字母 / 数字串，或单个 CJK 字符（无分词器时按字匹配，可覆盖中文 description）
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """把索引文本切分为词元。

    `qualified_name` 中的 `.` / `_` 天然作为分隔符（`github.list_issues` -> 3 个词元）；
    中文按单字切分，V1 不引入分词依赖。
    """
    return _TOKEN_RE.findall(_CAMEL_BOUNDARY.sub(" ", text).lower())


class TfidfToolSelector:
    """进程内 TF-IDF + cosine 的 Tool 选择器（设计文档 §7.2）。

    索引文本 = `qualified_name + description + server_name`。
    每次 `select` 都以「本次传入的 tools」为语料重建向量：候选范围即 Agent 已绑定且
    enabled 的 Tool，语料随 Agent 变化，无法预先全局建索引。
    """

    async def select(
        self,
        query: str,
        tools: list[ToolDefinition],
        top_k: int = 5,
    ) -> list[ToolCandidate]:
        if not tools or top_k <= 0:
            return []

        documents = [self._document(tool) for tool in tools]
        counts = [Counter(tokenize(document)) for document in documents]
        idf = self._idf(counts)
        tool_vectors = [self._vector(counter, idf) for counter in counts]
        query_vector = self._vector(Counter(tokenize(query)), idf)

        scored = [
            (self._cosine(query_vector, tool_vector), index)
            for index, tool_vector in enumerate(tool_vectors)
        ]
        # 得分降序；同分时保持传入顺序，保证结果稳定
        scored.sort(key=lambda item: (-item[0], item[1]))

        return [
            ToolCandidate(tool=tools[index], score=round(score, 6))
            for score, index in scored[:top_k]
        ]

    @staticmethod
    def _document(tool: ToolDefinition) -> str:
        return f"{tool.qualified_name} {tool.description} {tool.server_name}"

    @staticmethod
    def _idf(counts: list[Counter[str]]) -> dict[str, float]:
        """平滑 IDF：`ln((1+N)/(1+df)) + 1`，避免未见词元除零。"""
        total = len(counts)
        document_frequency: Counter[str] = Counter()
        for counter in counts:
            document_frequency.update(counter.keys())
        return {
            term: math.log((1 + total) / (1 + frequency)) + 1.0
            for term, frequency in document_frequency.items()
        }

    @staticmethod
    def _vector(counter: Counter[str], idf: dict[str, float]) -> dict[str, float]:
        """TF-IDF 并对向量做 L2 归一化，使内积即为 cosine 相似度。"""
        if not counter:
            return {}
        default_idf = math.log(len(idf) + 2.0) + 1.0  # 语料中未出现的词元
        total = sum(counter.values())
        weights = {
            term: (count / total) * idf.get(term, default_idf)
            for term, count in counter.items()
        }
        norm = math.sqrt(sum(weight * weight for weight in weights.values()))
        if norm == 0.0:
            return {}
        return {term: weight / norm for term, weight in weights.items()}

    @staticmethod
    def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
        if not left or not right:
            return 0.0
        # 遍历较短的一侧，减少查表次数
        shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
        return sum(weight * longer.get(term, 0.0) for term, weight in shorter.items())
