"""ModelGateway 单元测试（V2：用户级模型凭据）。

只验证凭据校验、缓存、能力校验、错误归类与脱敏，不发起真实网络请求。
"""

from __future__ import annotations

import pytest
from langchain_core.language_models import BaseChatModel

from app.agent.model_gateway import (
    ModelCredential,
    ModelErrorCode,
    ModelGateway,
    ModelGatewayError,
    classify_model_error,
    resolve_base_url,
)


def credential(**overrides: object) -> ModelCredential:
    base: dict[str, object] = {
        "provider": "deepseek",
        "model_key": "deepseek-chat",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-very-secret",
        "model_api_id": 7,
        "model_api_name": "我的 DeepSeek",
    }
    return ModelCredential(**{**base, **overrides})


class RecordingFactory:
    """记录构建入参的客户端工厂。"""

    def __init__(self) -> None:
        self.credentials: list[ModelCredential] = []

    def __call__(self, cred: ModelCredential) -> BaseChatModel:
        self.credentials.append(cred)
        return object()  # type: ignore[return-value]


def test_builds_client_with_credential_fields() -> None:
    factory = RecordingFactory()
    gateway = ModelGateway(factory)

    gateway.build(credential())

    assert len(factory.credentials) == 1
    built = factory.credentials[0]
    assert built.provider == "deepseek"
    assert built.model_key == "deepseek-chat"
    assert built.base_url == "https://api.deepseek.com/v1"


def test_same_credential_is_cached() -> None:
    factory = RecordingFactory()
    gateway = ModelGateway(factory)

    first = gateway.build(credential())
    second = gateway.build(credential())

    assert first is second
    assert len(factory.credentials) == 1


def test_changing_api_key_or_model_key_misses_cache() -> None:
    factory = RecordingFactory()
    gateway = ModelGateway(factory)

    gateway.build(credential())
    gateway.build(credential(api_key="sk-another"))
    gateway.build(credential(model_key="deepseek-reasoner"))

    assert len(factory.credentials) == 3


def test_cache_can_be_disabled() -> None:
    factory = RecordingFactory()
    gateway = ModelGateway(factory, cache_size=0)

    assert gateway.build(credential()) is not gateway.build(credential())
    assert len(factory.credentials) == 2


def test_runtime_error_message_is_sanitized() -> None:
    def exploding(_cred: ModelCredential) -> BaseChatModel:
        raise RuntimeError("bad request with key sk-very-secret")

    gateway = ModelGateway(exploding)

    with pytest.raises(ModelGatewayError) as info:
        gateway.build(credential())

    assert info.value.code == ModelErrorCode.CONFIG.value
    assert "sk-very-secret" not in info.value.message
    assert "***" in info.value.message


def test_requires_tool_call_capability() -> None:
    gateway = ModelGateway(RecordingFactory())

    with pytest.raises(ModelGatewayError) as info:
        gateway.build(credential(supports_tool_call=False), require_tool_call=True)

    assert info.value.code == ModelErrorCode.TOOL_CALL_UNSUPPORTED.value


def test_non_tool_call_model_is_allowed_when_no_tools() -> None:
    gateway = ModelGateway(RecordingFactory())
    assert gateway.build(credential(supports_tool_call=False)) is not None


def test_credential_rejects_empty_fields() -> None:
    with pytest.raises(ModelGatewayError) as info:
        ModelCredential(provider="", model_key="x", base_url="https://x", api_key="k")

    assert info.value.code == ModelErrorCode.CONFIG.value
    assert "provider" in info.value.message


def test_credential_repr_does_not_leak_api_key() -> None:
    assert "sk-very-secret" not in repr(credential())


def test_trace_meta_whitelists_model_fields_only() -> None:
    meta = credential().trace_meta()

    assert meta["model"] == "deepseek-chat"
    assert meta["model_key"] == "deepseek-chat"
    assert meta["model_api_id"] == 7
    assert meta["model_api_name"] == "我的 DeepSeek"
    assert "api_key" not in meta
    assert "base_url" not in meta


class _StatusError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"upstream error {status_code}")
        self.status_code = status_code


@pytest.mark.parametrize(
    ("status_code", "expected", "retryable"),
    [
        (401, ModelErrorCode.AUTH, False),
        (403, ModelErrorCode.AUTH, False),
        (404, ModelErrorCode.NOT_FOUND, False),
        (429, ModelErrorCode.RATE_LIMITED, True),
        (400, ModelErrorCode.BAD_REQUEST, False),
        (503, ModelErrorCode.UNAVAILABLE, True),
    ],
)
def test_classify_by_status_code(
    status_code: int,
    expected: ModelErrorCode,
    retryable: bool,
) -> None:
    assert classify_model_error(_StatusError(status_code)) == (expected.value, retryable)


def test_classify_timeout_by_exception_type() -> None:
    class APITimeoutError(RuntimeError):
        pass

    assert classify_model_error(APITimeoutError("boom")) == (ModelErrorCode.TIMEOUT.value, True)


def test_classify_unknown_falls_back_to_v1_code() -> None:
    """未识别异常仍回落到 V1 的 MODEL_ERROR，避免破坏既有前端。"""
    assert classify_model_error(RuntimeError("connection reset")) == ("MODEL_ERROR", False)


def test_resolve_base_url_uses_provider_default() -> None:
    assert resolve_base_url("qwen") == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert resolve_base_url("qwen", "https://proxy/v1") == "https://proxy/v1"


def test_unknown_provider_requires_explicit_base_url() -> None:
    with pytest.raises(ModelGatewayError, match="base_url"):
        resolve_base_url("my-gateway")
