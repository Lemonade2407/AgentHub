"""Model API 管理服务（修改意见文档 §3.3 / WP-1.2 / WP-1.3）。

归属：D（Platform Backend）。职责：
- 用户级 CRUD，所有查询按 `owner_id` 收敛；
- 密钥 Fernet 加密存储，任何响应只返回末 4 位提示；
- 连通性测试（GET /models），失败返回可读原因且不泄露密钥；
- 模型清单维护与默认模型设置。
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import httpx
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import SecretDecryptError, decrypt_secret, encrypt_secret, key_hint
from app.core.errors import AppError
from app.models.model_api import ModelApi, ModelApiModel
from app.schemas.model_api import (
    ModelApiCreate,
    ModelApiModelCreate,
    ModelApiModelRead,
    ModelApiModelUpdate,
    ModelApiOption,
    ModelApiRead,
    ModelApiTestResult,
    ModelApiUpdate,
)

MODEL_TEST_TIMEOUT_SECONDS = 10.0


class ModelApiService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # API CRUD
    # ------------------------------------------------------------------

    async def list(self, owner_id: int) -> list[ModelApiRead]:
        apis = (
            (
                await self._session.execute(
                    select(ModelApi)
                    .where(ModelApi.owner_id == owner_id)
                    .order_by(ModelApi.is_default.desc(), ModelApi.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        if not apis:
            return []
        models = await self._bulk_models([api.id for api in apis])
        return [self._to_read(api, models.get(api.id, [])) for api in apis]

    async def available(self, owner_id: int) -> list[ModelApiOption]:
        apis = (
            (
                await self._session.execute(
                    select(ModelApi)
                    .where(ModelApi.owner_id == owner_id, ModelApi.enabled.is_(True))
                    .order_by(ModelApi.is_default.desc(), ModelApi.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        if not apis:
            return []
        models = await self._bulk_models([api.id for api in apis], enabled_only=True)
        return [
            ModelApiOption(
                id=api.id,
                name=api.name,
                provider=api.provider,
                models=models.get(api.id, []),
            )
            for api in apis
        ]

    async def get(self, owner_id: int, api_id: int) -> ModelApiRead:
        api = await self._get_owned(owner_id, api_id)
        models = await self._models_for(api.id)
        return self._to_read(api, models)

    async def create(self, owner_id: int, payload: ModelApiCreate) -> ModelApiRead:
        try:
            cipher = encrypt_secret(payload.api_key)
        except SecretDecryptError as exc:
            raise AppError(
                "SECRET_DECRYPT_FAILED",
                "服务端未配置 SECRET_KEY，无法加密模型密钥",
                http_status=500,
            ) from exc

        if payload.is_default:
            await self._clear_default_api(owner_id, exclude_id=None)

        api = ModelApi(
            owner_id=owner_id,
            name=payload.name,
            provider=payload.provider.value,
            base_url=payload.base_url,
            api_key_cipher=cipher,
            api_key_hint=key_hint(payload.api_key),
            is_default=payload.is_default,
            enabled=payload.enabled,
        )
        self._session.add(api)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise AppError("CONFLICT", f"模型 API 名称已存在：{payload.name}", http_status=409) from exc
        await self._session.refresh(api)
        return self._to_read(api, [])

    async def update(self, owner_id: int, api_id: int, payload: ModelApiUpdate) -> ModelApiRead:
        api = await self._get_owned(owner_id, api_id)
        data = payload.model_dump(exclude_unset=True)

        if data.get("api_key"):
            try:
                api.api_key_cipher = encrypt_secret(data.pop("api_key"))
            except SecretDecryptError as exc:
                raise AppError(
                    "SECRET_DECRYPT_FAILED",
                    "服务端未配置 SECRET_KEY，无法加密模型密钥",
                    http_status=500,
                ) from exc
            api.api_key_hint = key_hint(payload.api_key or "")
        else:
            data.pop("api_key", None)

        if data.get("is_default") is True:
            await self._clear_default_api(owner_id, exclude_id=api.id)

        for field, value in data.items():
            if value is None:
                raise AppError("INVALID_ARGUMENT", f"字段 {field} 不能为 null", http_status=400)
            if hasattr(value, "value"):
                value = value.value
            setattr(api, field, value)

        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise AppError("CONFLICT", "模型 API 名称已存在", http_status=409) from exc
        await self._session.refresh(api)
        models = await self._models_for(api.id)
        return self._to_read(api, models)

    async def delete(self, owner_id: int, api_id: int) -> None:
        api = await self._get_owned(owner_id, api_id)
        if await self._is_referenced_by_agent(api.id):
            raise AppError(
                "MODEL_API_IN_USE",
                "该模型 API 仍被 Agent 引用，请先切换 Agent 的模型",
                http_status=409,
            )
        await self._session.delete(api)
        await self._session.flush()

    # ------------------------------------------------------------------
    # 模型清单
    # ------------------------------------------------------------------

    async def list_models(self, owner_id: int, api_id: int) -> list[ModelApiModelRead]:
        await self._get_owned(owner_id, api_id)
        return await self._models_for(api_id)

    async def add_model(
        self, owner_id: int, api_id: int, payload: ModelApiModelCreate
    ) -> ModelApiModelRead:
        await self._get_owned(owner_id, api_id)
        if payload.is_default:
            await self._clear_default_model(api_id, exclude_id=None)

        exists = (
            await self._session.execute(
                select(ModelApiModel.id).where(
                    ModelApiModel.model_api_id == api_id,
                    ModelApiModel.model_key == payload.model_key,
                )
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise AppError("CONFLICT", f"模型已存在：{payload.model_key}", http_status=409)

        model = ModelApiModel(
            model_api_id=api_id,
            model_key=payload.model_key,
            display_name=payload.display_name or payload.model_key,
            capabilities=payload.capabilities,
            enabled=payload.enabled,
            is_default=payload.is_default,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_model_read(model)

    async def update_model(
        self,
        owner_id: int,
        api_id: int,
        model_id: int,
        payload: ModelApiModelUpdate,
    ) -> ModelApiModelRead:
        await self._get_owned(owner_id, api_id)
        model = await self._get_model(api_id, model_id)
        data = payload.model_dump(exclude_unset=True)
        if data.get("is_default") is True:
            await self._clear_default_model(api_id, exclude_id=model.id)
        for field, value in data.items():
            if value is None and field in {"display_name", "enabled", "is_default"}:
                raise AppError("INVALID_ARGUMENT", f"字段 {field} 不能为 null", http_status=400)
            setattr(model, field, value)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_model_read(model)

    async def delete_model(self, owner_id: int, api_id: int, model_id: int) -> None:
        await self._get_owned(owner_id, api_id)
        model = await self._get_model(api_id, model_id)
        await self._session.delete(model)
        await self._session.flush()

    # ------------------------------------------------------------------
    # 连通性测试
    # ------------------------------------------------------------------

    async def test(self, owner_id: int, api_id: int) -> ModelApiTestResult:
        api = await self._get_owned(owner_id, api_id)
        try:
            api_key = decrypt_secret(api.api_key_cipher)
        except SecretDecryptError as exc:
            raise AppError(
                "SECRET_DECRYPT_FAILED",
                "模型 API Key 解密失败，请重新保存密钥",
                http_status=500,
            ) from exc

        url = f"{api.base_url.rstrip('/')}/models"
        started = time.perf_counter()
        ok = False
        models: list[str] = []
        error: str | None = None
        try:
            async with httpx.AsyncClient(timeout=MODEL_TEST_TIMEOUT_SECONDS) as client:
                resp = await client.get(
                    url, headers={"Authorization": f"Bearer {api_key}"}
                )
            if resp.status_code >= 400:
                error = f"上游返回 HTTP {resp.status_code}：{resp.text[:200]}"
            else:
                body = resp.json()
                data = body.get("data") if isinstance(body, dict) else None
                if isinstance(data, list):
                    models = [
                        str(item.get("id"))
                        for item in data
                        if isinstance(item, dict) and item.get("id")
                    ]
                ok = True
        except httpx.TimeoutException:
            error = "连接超时（10s）"
        except httpx.HTTPError as exc:
            error = f"网络错误：{type(exc).__name__}"
        except ValueError:
            error = "上游返回的不是合法 JSON"

        latency_ms = int((time.perf_counter() - started) * 1000)
        api.last_test_at = datetime.now(UTC)
        api.last_test_ok = ok
        api.last_error = None if ok else (error or "测试失败")[:512]
        await self._session.flush()
        return ModelApiTestResult(
            ok=ok,
            latency_ms=latency_ms,
            models=models,
            error=None if ok else api.last_error,
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _get_owned(self, owner_id: int, api_id: int) -> ModelApi:
        api = (
            await self._session.execute(
                select(ModelApi).where(ModelApi.id == api_id, ModelApi.owner_id == owner_id)
            )
        ).scalar_one_or_none()
        if api is None:
            raise AppError(
                "MODEL_API_NOT_FOUND", f"模型 API 不存在：{api_id}", http_status=404
            )
        return api

    async def _get_model(self, api_id: int, model_id: int) -> ModelApiModel:
        model = (
            await self._session.execute(
                select(ModelApiModel).where(
                    ModelApiModel.id == model_id,
                    ModelApiModel.model_api_id == api_id,
                )
            )
        ).scalar_one_or_none()
        if model is None:
            raise AppError("MODEL_NOT_AVAILABLE", "模型不存在", http_status=404)
        return model

    async def _models_for(self, api_id: int) -> list[ModelApiModelRead]:
        rows = (
            (
                await self._session.execute(
                    select(ModelApiModel)
                    .where(ModelApiModel.model_api_id == api_id)
                    .order_by(ModelApiModel.is_default.desc(), ModelApiModel.id)
                )
            )
            .scalars()
            .all()
        )
        return [self._to_model_read(row) for row in rows]

    async def _bulk_models(
        self, api_ids: list[int], *, enabled_only: bool = False
    ) -> dict[int, list[ModelApiModelRead]]:
        if not api_ids:
            return {}
        conditions = [ModelApiModel.model_api_id.in_(api_ids)]
        if enabled_only:
            conditions.append(ModelApiModel.enabled.is_(True))
        rows = (
            (
                await self._session.execute(
                    select(ModelApiModel)
                    .where(*conditions)
                    .order_by(ModelApiModel.is_default.desc(), ModelApiModel.id)
                )
            )
            .scalars()
            .all()
        )
        result: dict[int, list[ModelApiModelRead]] = {}
        for row in rows:
            result.setdefault(row.model_api_id, []).append(self._to_model_read(row))
        return result

    async def _clear_default_api(self, owner_id: int, *, exclude_id: int | None) -> None:
        stmt = update(ModelApi).where(ModelApi.owner_id == owner_id)
        if exclude_id is not None:
            stmt = stmt.where(ModelApi.id != exclude_id)
        await self._session.execute(stmt.values(is_default=False))

    async def _clear_default_model(self, api_id: int, *, exclude_id: int | None) -> None:
        stmt = update(ModelApiModel).where(ModelApiModel.model_api_id == api_id)
        if exclude_id is not None:
            stmt = stmt.where(ModelApiModel.id != exclude_id)
        await self._session.execute(stmt.values(is_default=False))

    async def _is_referenced_by_agent(self, api_id: int) -> bool:
        columns = set(
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
        if "model_api_id" not in columns:
            return False
        return (
            await self._session.execute(
                text("SELECT 1 FROM agent WHERE model_api_id = :id LIMIT 1"),
                {"id": api_id},
            )
        ).first() is not None

    @staticmethod
    def _to_model_read(model: ModelApiModel) -> ModelApiModelRead:
        return ModelApiModelRead(
            id=model.id,
            model_key=model.model_key,
            display_name=model.display_name,
            capabilities=dict(model.capabilities or {}),
            enabled=model.enabled,
            is_default=model.is_default,
        )

    def _to_read(self, api: ModelApi, models: list[ModelApiModelRead]) -> ModelApiRead:
        return ModelApiRead(
            id=api.id,
            name=api.name,
            provider=api.provider,
            base_url=api.base_url,
            api_key_hint=api.api_key_hint,
            is_default=api.is_default,
            enabled=api.enabled,
            last_test_at=api.last_test_at,
            last_test_ok=api.last_test_ok,
            last_error=api.last_error,
            models=models,
        )
