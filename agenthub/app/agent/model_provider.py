"""LLM 接入。设计文档 §3 / §14.1。归属：A（Agent Runtime）。

统一走 OpenAI-compatible 接口，从而兼容 DeepSeek / Qwen / 自建网关。
`model` 字段格式固定为 `provider/model`（契约 §2.8）。
"""

from __future__ import annotations

import os

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

# 设计文档 §14.1：LLM 请求超时 60s
LLM_TIMEOUT_SECONDS = 60

# provider -> (默认 base_url, 专用 API Key 环境变量名)
_PROVIDER_DEFAULTS: dict[str, tuple[str, str]] = {
    "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
}


class ModelConfigError(ValueError):
    """`model` 字符串不合法，或缺少可用的凭据 / base_url。"""


def build_chat_model(model: str, *, temperature: float = 0.0) -> BaseChatModel:
    """按 `provider/model` 构建 ChatModel。

    `LLM_BASE_URL` / `LLM_API_KEY` 可覆盖 provider 默认值，用于自建网关或代理场景。
    """
    provider, _, name = model.partition("/")
    if not provider or not name:
        raise ModelConfigError(f"model 必须为 'provider/model' 形式，收到：{model!r}")

    default_base_url, api_key_env = _PROVIDER_DEFAULTS.get(provider, ("", "LLM_API_KEY"))
    base_url = os.getenv("LLM_BASE_URL") or default_base_url
    if not base_url:
        raise ModelConfigError(f"未知 provider {provider!r}，请设置 LLM_BASE_URL")

    api_key = os.getenv("LLM_API_KEY") or os.getenv(api_key_env)
    if not api_key:
        raise ModelConfigError(
            f"缺少 {provider!r} 的 API Key：请设置 {api_key_env} 或 LLM_API_KEY"
        )

    return ChatOpenAI(
        model=name,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        timeout=LLM_TIMEOUT_SECONDS,
    )
