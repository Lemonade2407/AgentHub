"""ModelProvider 单元测试（设计文档 §3 / §14.1）。

只验证配置解析与失败路径，不发起真实网络请求。
"""

from __future__ import annotations

import pytest
from langchain_openai import ChatOpenAI

from app.agent.model_provider import LLM_TIMEOUT_SECONDS, ModelConfigError, build_chat_model


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_rejects_model_without_provider_prefix() -> None:
    with pytest.raises(ModelConfigError):
        build_chat_model("deepseek-chat")


def test_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ModelConfigError, match="DEEPSEEK_API_KEY"):
        build_chat_model("deepseek/deepseek-chat")


def test_unknown_provider_requires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    with pytest.raises(ModelConfigError, match="LLM_BASE_URL"):
        build_chat_model("custom/some-model")


def test_builds_openai_compatible_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    model = build_chat_model("deepseek/deepseek-chat", temperature=0.2)

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "deepseek-chat"
    assert str(model.openai_api_base) == "https://api.deepseek.com/v1"
    assert model.temperature == 0.2
    # 设计文档 §14.1：LLM 请求超时 60s
    assert model.request_timeout == LLM_TIMEOUT_SECONDS


def test_env_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-proxy")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.internal/v1")

    model = build_chat_model("qwen/qwen-plus")

    assert model.model_name == "qwen-plus"
    assert str(model.openai_api_base) == "https://gateway.internal/v1"
