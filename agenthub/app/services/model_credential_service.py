"""Agent 模型凭据解析。归属：D（平台数据）+ B（模型能力校验协同）。

V1 的 `AgentRunner` 直接读环境变量；V2 要求按 Agent 引用的 Model API 解密取 Key。
本模块负责把数据库中的 `agent.model_api_id / model_key` 解析成 `ModelCredential`：

- 没有 V2 字段或字段为空 → 返回 `None`，Runtime 回落到 V1 环境变量路径；
- 引用的 Model API 被禁用 / 模型不在清单 → `MODEL_NOT_AVAILABLE`；
- 密钥解密失败 → `SECRET_DECRYPT_FAILED`；
- `capabilities.tool_call = false` 时，Runtime 会因工具调用能力不足而拒绝运行。

密钥只存在于内存与 `ModelCredential` 中，`repr=False`，不写日志 / Trace。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.model_gateway import ModelCredential, ModelGatewayError
from app.core.crypto import SecretDecryptError, decrypt_secret
from app.core.errors import AppError
from app.models.model_api import ModelApi, ModelApiModel


class ModelCredentialResolver:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve(self, agent_id: int) -> ModelCredential | None:
        columns = await self._agent_columns()
        if "model_api_id" not in columns or "model_key" not in columns:
            return None

        row = (
            await self._session.execute(
                text("SELECT model_api_id, model_key FROM agent WHERE id = :agent_id"),
                {"agent_id": agent_id},
            )
        ).first()
        if row is None or row[0] is None or not row[1]:
            return None
        model_api_id, model_key = int(row[0]), str(row[1])

        api = await self._session.get(ModelApi, model_api_id)
        if api is None or not api.enabled:
            raise AppError(
                "MODEL_NOT_AVAILABLE",
                "Agent 引用的 Model API 不存在或已禁用，请重新选择模型",
                http_status=409,
                detail={"model_api_id": model_api_id},
            )

        model = (
            await self._session.execute(
                select(ModelApiModel).where(
                    ModelApiModel.model_api_id == model_api_id,
                    ModelApiModel.model_key == model_key,
                    ModelApiModel.enabled.is_(True),
                )
            )
        ).scalar_one_or_none()
        if model is None:
            raise AppError(
                "MODEL_NOT_AVAILABLE",
                f"模型 {model_key} 不在该 Model API 的可用清单中",
                http_status=409,
                detail={"model_api_id": model_api_id, "model_key": model_key},
            )

        try:
            api_key = decrypt_secret(api.api_key_cipher)
        except SecretDecryptError as exc:
            raise AppError(
                "SECRET_DECRYPT_FAILED",
                "模型 API Key 解密失败，请重新保存密钥",
                http_status=500,
                detail={"model_api_id": model_api_id},
            ) from exc

        capabilities: dict[str, Any] = model.capabilities or {}
        try:
            return ModelCredential(
                provider=api.provider,
                model_key=model.model_key,
                base_url=api.base_url,
                api_key=api_key,
                model_api_id=api.id,
                model_api_name=api.name,
                context_window=_as_positive_int(capabilities.get("context_window")),
                supports_tool_call=_as_bool(capabilities.get("tool_call"), default=True),
            )
        except ModelGatewayError as exc:
            raise AppError(
                exc.code,
                exc.message,
                http_status=400,
                detail={"model_api_id": model_api_id},
            ) from exc

    async def _agent_columns(self) -> set[str]:
        return set(
            (
                await self._session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'agent' AND table_schema = current_schema()"
                    )
                )
            )
            .scalars()
            .all()
        )


def _as_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off")
    return bool(value)


def _as_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
