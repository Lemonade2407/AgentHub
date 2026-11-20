"""Agent / Skill 工作区文件 DTO。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class WorkspaceFileRead(BaseModel):
    """工作区中的一个文件（元数据来自文件系统）。"""

    name: str
    size: int
    updated_at: datetime


class DocumentGenerateRequest(BaseModel):
    """生成文档并保存到 Agent 工作区。"""

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=100_000)
    format: Literal["docx", "pdf"] = "docx"
    author: str = Field(default="", max_length=100)
