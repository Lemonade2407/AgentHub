"""Model API DTO（修改意见文档 §3.3，Contract v2.0）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.enums import ModelProvider


class ModelApiModelCreate(BaseModel):
    model_key: str = Field(min_length=1, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    is_default: bool = False


class ModelApiModelUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    capabilities: dict[str, Any] | None = None
    enabled: bool | None = None
    is_default: bool | None = None


class ModelApiModelRead(BaseModel):
    id: int
    model_key: str
    display_name: str
    capabilities: dict[str, Any] = Field(default_factory=dict)
    enabled: bool
    is_default: bool


class ModelApiCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    provider: ModelProvider = ModelProvider.DEEPSEEK
    base_url: str = Field(min_length=1, max_length=512)
    api_key: str = Field(min_length=1, max_length=1024)
    is_default: bool = False
    enabled: bool = True


class ModelApiUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    provider: ModelProvider | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=512)
    # 留空表示不修改密钥
    api_key: str | None = Field(default=None, max_length=1024)
    is_default: bool | None = None
    enabled: bool | None = None


class ModelApiRead(BaseModel):
    id: int
    name: str
    provider: str
    base_url: str
    api_key_hint: str | None
    is_default: bool
    enabled: bool
    last_test_at: datetime | None
    last_test_ok: bool | None
    last_error: str | None
    models: list[ModelApiModelRead] = Field(default_factory=list)


class ModelApiTestResult(BaseModel):
    ok: bool
    latency_ms: int | None = None
    models: list[str] = Field(default_factory=list)
    error: str | None = None


class ModelApiOption(BaseModel):
    id: int
    name: str
    provider: str
    models: list[ModelApiModelRead] = Field(default_factory=list)
