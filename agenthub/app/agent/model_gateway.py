"""V2 模型网关。归属：A（Agent Runtime）。

V1 的 `model_provider.build_chat_model` 只支持**进程级环境变量**；V2 的模型凭据由
D 从 `model_api` 表读取并解密后，以 `ModelCredential` 的形式交给本模块。因此本模块：

- 不依赖数据库、不负责解密、不持有 ORM 实体；
- 负责按凭据构建 ChatModel、按凭据缓存、把上游异常归类为契约错误码、对错误信息脱敏；
- 保留 `provider/model` 的降级路径（见 `model_provider.build_chat_model`）。

Trace 中只允许出现 `model_api_id / model_api_name / model_key`，**禁止**出现 `api_key`。
"""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

# 设计文档 §14.1：LLM 请求超时 60s
LLM_TIMEOUT_SECONDS = 60
# 缓存上限：按「凭据指纹」缓存客户端，避免每次 Run 重建连接池
DEFAULT_CACHE_SIZE = 32

# provider 默认地址；`base_url` 允许用户覆盖（自建网关 / 代理）
PROVIDER_DEFAULT_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}


class ModelErrorCode(StrEnum):
    """模型侧错误码（契约 V2 新增，写入 Run.error_code 与 Trace）。"""

    CONFIG = "MODEL_CONFIG_ERROR"
    AUTH = "MODEL_AUTH_ERROR"
    NOT_FOUND = "MODEL_NOT_FOUND"
    RATE_LIMITED = "MODEL_RATE_LIMITED"
    TIMEOUT = "MODEL_TIMEOUT"
    UNAVAILABLE = "MODEL_UNAVAILABLE"
    BAD_REQUEST = "MODEL_BAD_REQUEST"
    TOOL_CALL_UNSUPPORTED = "MODEL_TOOL_CALL_UNSUPPORTED"


class ModelGatewayError(RuntimeError):
    """模型接入/调用失败。`message` 保证已脱敏，可直接写入 Trace。"""

    def __init__(
        self,
        code: ModelErrorCode | str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = message
        self.retryable = retryable

    def to_trace(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


@dataclass(frozen=True)
class ModelCredential:
    """D 解密后传入的一条可用模型凭据。

    `api_key` 标记 `repr=False`，避免异常日志 / 调试打印时泄露。
    """

    provider: str
    model_key: str
    base_url: str
    api_key: str = field(repr=False)
    model_api_id: int | None = None
    model_api_name: str | None = None
    context_window: int | None = None
    supports_tool_call: bool = True
    temperature: float = 0.0
    timeout_seconds: int = LLM_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        for name in ("provider", "model_key", "base_url", "api_key"):
            if not str(getattr(self, name) or "").strip():
                raise ModelGatewayError(
                    ModelErrorCode.CONFIG,
                    f"模型凭据缺少必填字段：{name}",
                )
        if self.model_api_id is not None and self.model_api_id <= 0:
            raise ModelGatewayError(ModelErrorCode.CONFIG, "model_api_id 必须为正整数")

    def trace_meta(self) -> dict[str, object]:
        """写入 Trace 的模型标识（白名单，绝不含密钥与 base_url）。"""
        meta: dict[str, object] = {
            "model": self.model_key,
            "model_key": self.model_key,
            "provider": self.provider,
        }
        if self.model_api_id is not None:
            meta["model_api_id"] = self.model_api_id
        if self.model_api_name:
            meta["model_api_name"] = self.model_api_name
        return meta


class ModelGateway:
    """按 `ModelCredential` 构建并缓存 ChatModel。

    `client_factory` 可注入，测试时用它替代真实网络客户端。
    """

    def __init__(
        self,
        client_factory: Callable[[ModelCredential], BaseChatModel] | None = None,
        *,
        cache_size: int = DEFAULT_CACHE_SIZE,
    ) -> None:
        self._client_factory = client_factory or _build_openai_compatible_client
        self._cache_size = max(0, cache_size)
        self._cache: OrderedDict[str, BaseChatModel] = OrderedDict()

    def build(
        self,
        credential: ModelCredential,
        *,
        require_tool_call: bool = False,
    ) -> BaseChatModel:
        """构建（或复用）模型客户端。

        `require_tool_call=True` 时校验模型能力：模型不支持 tool calling 却绑定了工具，
        属于配置错误，提前失败比运行到一半再报错更可读。
        """
        if require_tool_call and not credential.supports_tool_call:
            raise ModelGatewayError(
                ModelErrorCode.TOOL_CALL_UNSUPPORTED,
                f"模型 {credential.model_key} 不支持 tool calling，"
                "请改用支持工具调用的模型或取消工具绑定",
            )

        cache_key = self.cache_key(credential)
        if self._cache_size:
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache.move_to_end(cache_key)
                return cached

        try:
            model = self._client_factory(credential)
        except ModelGatewayError:
            raise
        except Exception as exc:  # 构建期异常多为配置错误（地址/参数不合法）
            raise ModelGatewayError(
                ModelErrorCode.CONFIG,
                _sanitize(f"{type(exc).__name__}: {exc}", credential.api_key)[:512],
            ) from None

        if self._cache_size:
            self._cache[cache_key] = model
            self._cache.move_to_end(cache_key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return model

    @staticmethod
    def cache_key(credential: ModelCredential) -> str:
        """凭据指纹：包含密钥摘要，确保换 Key 后不会命中旧客户端；指纹不可逆。"""
        raw = "|".join(
            [
                credential.provider,
                credential.base_url,
                credential.model_key,
                hashlib.sha256(credential.api_key.encode("utf-8")).hexdigest(),
                str(credential.temperature),
                str(credential.timeout_seconds),
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def clear_cache(self) -> None:
        self._cache.clear()


def _build_openai_compatible_client(credential: ModelCredential) -> BaseChatModel:
    """所有 provider 统一走 OpenAI-compatible 协议（设计文档 §3）。"""
    return ChatOpenAI(
        model=credential.model_key,
        base_url=credential.base_url,
        api_key=credential.api_key,
        temperature=credential.temperature,
        timeout=credential.timeout_seconds,
    )


def resolve_base_url(provider: str, base_url: str | None = None) -> str:
    """用户未填 base_url 时按 provider 取默认值；未知 provider 必须显式提供。"""
    if base_url:
        return base_url
    default = PROVIDER_DEFAULT_BASE_URLS.get(provider)
    if not default:
        raise ModelGatewayError(
            ModelErrorCode.CONFIG,
            f"未知 provider {provider!r}，请填写 base_url",
        )
    return default


def classify_model_error(exc: BaseException) -> tuple[str, bool]:
    """把上游异常归类为（错误码, 是否可重试）。

    只做保守映射：无法归类的仍回落到契约 V1 的 `MODEL_ERROR`，
    避免破坏既有前端对错误码的容忍逻辑。
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status in (401, 403):
            return ModelErrorCode.AUTH.value, False
        if status == 404:
            return ModelErrorCode.NOT_FOUND.value, False
        if status == 429:
            return ModelErrorCode.RATE_LIMITED.value, True
        if status == 400:
            return ModelErrorCode.BAD_REQUEST.value, False
        if 500 <= status < 600:
            return ModelErrorCode.UNAVAILABLE.value, True

    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timed out" in text or "timeouterror" in name:
        return ModelErrorCode.TIMEOUT.value, True
    if "rate limit" in text or "quota" in text:
        return ModelErrorCode.RATE_LIMITED.value, True
    if "unauthorized" in text or "invalid api key" in text or "401" in text:
        return ModelErrorCode.AUTH.value, False
    return "MODEL_ERROR", False


def _sanitize(text: str, secret: str) -> str:
    """从文本中移除密钥。空密钥不参与替换，避免把空串替换成 `***`。"""
    if secret:
        return text.replace(secret, "***")
    return text
