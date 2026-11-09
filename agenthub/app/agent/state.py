"""Agent 单次运行态。设计文档 §6.2。归属：A（Agent Runtime）。

注意与 `AgentDefinition`（持久化配置）的边界：本对象只存在于一次 Run 的执行过程中。
V1 不实现跨 Agent 的长期记忆（设计文档 §5.1）。
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from app.mcp.schemas import ToolDefinition


class AgentState(TypedDict):
    """LangGraph 图状态。

    `step_count` 为已完成的图执行步数（= 节点执行次数），语义见契约 §3.4；
    图节点每次执行时将其推进 1，`max_steps` 的限制对象即此计数。
    """

    messages: Annotated[list[BaseMessage], add_messages]
    candidate_tools: list[ToolDefinition]
    step_count: int
    run_id: str
    final_answer: str | None
