"""TF-IDF Tool Selector 单测（设计文档 §7、§17）。"""

from __future__ import annotations

from app.tools.selector import TfidfToolSelector, ToolSelector
from tests.mcp_fakes import make_tool


def build_selector() -> TfidfToolSelector:
    return TfidfToolSelector()


def sample_tools():
    return [
        make_tool("github.list_issues", description="List open issues in a repository"),
        make_tool("search.search_web", description="Search the web for information"),
        make_tool("db.query_users", description="Query the user table"),
    ]


async def test_ranks_relevant_tool_first() -> None:
    selector = build_selector()

    candidates = await selector.select("open issues in repository", sample_tools())

    assert candidates[0].tool.qualified_name == "github.list_issues"
    assert candidates[0].score > 0
    scores = [candidate.score for candidate in candidates]
    assert scores == sorted(scores, reverse=True)


async def test_respects_top_k() -> None:
    selector = build_selector()

    candidates = await selector.select("open issues in repository", sample_tools(), top_k=1)

    assert len(candidates) == 1
    assert candidates[0].tool.qualified_name == "github.list_issues"


async def test_empty_tools_or_top_k_returns_empty() -> None:
    selector = build_selector()

    assert await selector.select("anything", []) == []
    assert await selector.select("anything", sample_tools(), top_k=0) == []


async def test_no_match_keeps_top_k_with_zero_scores() -> None:
    """查询无任何词元命中时，仍返回 Top-K（分数为 0），避免候选集被清空。"""
    selector = build_selector()

    candidates = await selector.select("zzzznomatch", sample_tools(), top_k=2)

    assert len(candidates) == 2
    assert all(candidate.score == 0.0 for candidate in candidates)
    # 同分时保持传入顺序，结果稳定
    assert [candidate.tool.qualified_name for candidate in candidates] == [
        "github.list_issues",
        "search.search_web",
    ]


async def test_matches_chinese_description() -> None:
    """中文 description 按单字匹配（不引入分词依赖）。"""
    selector = build_selector()
    tools = [
        make_tool("repo.list_issues", description="查询仓库中的问题单"),
        make_tool("web.search", description="搜索互联网信息"),
    ]

    candidates = await selector.select("查询问题单", tools)

    assert candidates[0].tool.qualified_name == "repo.list_issues"
    assert candidates[0].score > 0


async def test_implements_tool_selector_protocol() -> None:
    assert isinstance(build_selector(), ToolSelector)
