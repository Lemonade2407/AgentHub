"""模型 API 密钥的对称加解密（修改意见文档 §3.5，DB 设计文档 v2.0）。归属：D。

约定（冻结）：

- 算法：`cryptography.fernet`（AES-128-CBC + HMAC-SHA256）。
- 主密钥：环境变量 `SECRET_KEY`，**不落库、不写日志、不进 Trace**。
- 派生：对 `SECRET_KEY` 做 SHA-256 后 urlsafe-base64，得到 Fernet 要求的 32 字节密钥，
  因此 `SECRET_KEY` 可以是任意高熵字符串，无需预先符合 Fernet 格式。
- 解密失败（密钥轮换、密文损坏）抛出 `SecretDecryptError`，应用层映射为
  契约错误码 `SECRET_DECRYPT_FAILED`。

注意：Alembic 迁移脚本不依赖本模块（迁移需长期可重放，独立内嵌同一派生算法）；
修改本文件的派生方式必须同步修改迁移 `0002_v2_schema` 并提供重加密迁移。
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


class SecretDecryptError(RuntimeError):
    """密钥无法解密：主密钥缺失 / 被轮换，或密文已损坏。"""


def _fernet(secret_key: str) -> Fernet:
    digest = hashlib.sha256(secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str, *, secret_key: str | None = None) -> str:
    """加密明文密钥，返回 Fernet 密文（urlsafe-base64 字符串）。

    `secret_key` 缺省时读取环境变量 `SECRET_KEY`；缺失即抛 `SecretDecryptError`，
    因为"静默存明文"比直接失败更糟。
    """
    key = secret_key if secret_key is not None else os.getenv("SECRET_KEY", "")
    if not key:
        raise SecretDecryptError("缺少 SECRET_KEY 环境变量，无法加密模型 API Key")
    return _fernet(key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(cipher: str, *, secret_key: str | None = None) -> str:
    """解密 Fernet 密文。任何失败统一抛 `SecretDecryptError`，不泄露细节。"""
    key = secret_key if secret_key is not None else os.getenv("SECRET_KEY", "")
    if not key:
        raise SecretDecryptError("缺少 SECRET_KEY 环境变量，无法解密模型 API Key")
    try:
        return _fernet(key).decrypt(cipher.encode("ascii")).decode("utf-8")
    except InvalidToken:
        raise SecretDecryptError(
            "模型 API Key 解密失败：SECRET_KEY 与密文不匹配（可能已轮换）"
        ) from None


def key_hint(api_key: str) -> str:
    """取密钥末 4 位用于界面展示（DB 仅存末 4 位，展示层拼 `****` 前缀）。"""
    return api_key[-4:] if len(api_key) >= 4 else api_key
