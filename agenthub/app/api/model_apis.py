"""Model API 管理 API（修改意见文档 §3.3，WP-1.2 / WP-1.3）。

归属：D（Platform Backend）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_session
from app.models.user import AppUser
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
from app.services.model_api_service import ModelApiService

router = APIRouter(prefix="/api/model-apis", tags=["model-apis"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[AppUser, Depends(get_current_user)]


@router.get("", response_model=list[ModelApiRead])
async def list_model_apis(session: SessionDep, user: CurrentUser) -> list[ModelApiRead]:
    return await ModelApiService(session).list(user.id)


@router.post("", response_model=ModelApiRead, status_code=status.HTTP_201_CREATED)
async def create_model_api(
    payload: ModelApiCreate, session: SessionDep, user: CurrentUser
) -> ModelApiRead:
    api = await ModelApiService(session).create(user.id, payload)
    await session.commit()
    return api


@router.get("/available", response_model=list[ModelApiOption])
async def available_model_apis(session: SessionDep, user: CurrentUser) -> list[ModelApiOption]:
    """Agent 编辑器 / 模型选择器用的树形聚合。"""
    return await ModelApiService(session).available(user.id)


@router.get("/{api_id}", response_model=ModelApiRead)
async def get_model_api(api_id: int, session: SessionDep, user: CurrentUser) -> ModelApiRead:
    return await ModelApiService(session).get(user.id, api_id)


@router.put("/{api_id}", response_model=ModelApiRead)
async def update_model_api(
    api_id: int, payload: ModelApiUpdate, session: SessionDep, user: CurrentUser
) -> ModelApiRead:
    api = await ModelApiService(session).update(user.id, api_id, payload)
    await session.commit()
    return api


@router.delete("/{api_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_api(api_id: int, session: SessionDep, user: CurrentUser) -> Response:
    await ModelApiService(session).delete(user.id, api_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{api_id}/test", response_model=ModelApiTestResult)
async def test_model_api(
    api_id: int, session: SessionDep, user: CurrentUser
) -> ModelApiTestResult:
    result = await ModelApiService(session).test(user.id, api_id)
    await session.commit()
    return result


@router.get("/{api_id}/models", response_model=list[ModelApiModelRead])
async def list_models(
    api_id: int, session: SessionDep, user: CurrentUser
) -> list[ModelApiModelRead]:
    return await ModelApiService(session).list_models(user.id, api_id)


@router.post(
    "/{api_id}/models",
    response_model=ModelApiModelRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_model(
    api_id: int,
    payload: ModelApiModelCreate,
    session: SessionDep,
    user: CurrentUser,
) -> ModelApiModelRead:
    model = await ModelApiService(session).add_model(user.id, api_id, payload)
    await session.commit()
    return model


@router.put("/{api_id}/models/{model_id}", response_model=ModelApiModelRead)
async def update_model(
    api_id: int,
    model_id: int,
    payload: ModelApiModelUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> ModelApiModelRead:
    model = await ModelApiService(session).update_model(user.id, api_id, model_id, payload)
    await session.commit()
    return model


@router.delete("/{api_id}/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    api_id: int, model_id: int, session: SessionDep, user: CurrentUser
) -> Response:
    await ModelApiService(session).delete_model(user.id, api_id, model_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
