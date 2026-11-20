"""Agent / Skill 工作区文件 API。

- Agent 专属文件：`/api/agents/{agent_id}/files`
- Skill 公共资源库：`/api/skills/{skill_id}/attachments`
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import get_session
from app.models.user import AppUser
from app.repositories.agent_repository import AgentRepository
from app.repositories.skill_repository import SkillRepository
from app.schemas.workspace import DocumentGenerateRequest, WorkspaceFileRead
from app.services.workspace_service import (
    delete_file,
    ensure_agent_dir,
    ensure_skill_dir,
    list_files,
    resolve_file,
    save_file,
)
from document_mcp_server.server import build_docx, build_pdf, output_file

router = APIRouter(prefix="/api/agents", tags=["workspace"])
skill_router = APIRouter(prefix="/api/skills", tags=["workspace"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[AppUser, Depends(get_current_user)]


async def _agent_dir(agent_id: int, session: AsyncSession):
    await AgentRepository(session).get(agent_id)  # 404 校验
    return ensure_agent_dir(agent_id)


async def _skill_dir(
    skill_id: int,
    session: AsyncSession,
    user: AppUser,
    *,
    write: bool = False,
):
    skill = await SkillRepository(session).get_visible(owner_id=user.id, skill_id=skill_id)
    if write and not skill.owned:
        raise AppError(
            "FORBIDDEN",
            "只能管理自己 Skill 的附件",
            http_status=403,
        )
    return ensure_skill_dir(skill_id)


def _read_limit() -> int:
    return get_settings().max_upload_bytes


async def _upload(directory, file: UploadFile) -> WorkspaceFileRead:
    data = await file.read(_read_limit() + 1)
    stored = save_file(directory, file.filename or "upload.bin", data)
    return WorkspaceFileRead(
        name=stored.name,
        size=stored.size,
        updated_at=stored.updated_at,
    )


# ----------------------------------------------------------------------
# Agent 文件
# ----------------------------------------------------------------------


@router.get("/{agent_id}/files", response_model=list[WorkspaceFileRead])
async def list_agent_files(agent_id: int, session: SessionDep) -> list[WorkspaceFileRead]:
    directory = await _agent_dir(agent_id, session)
    return [
        WorkspaceFileRead(name=item.name, size=item.size, updated_at=item.updated_at)
        for item in list_files(directory)
    ]


@router.post(
    "/{agent_id}/files",
    response_model=WorkspaceFileRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_agent_file(
    agent_id: int,
    session: SessionDep,
    file: UploadFile = File(...),
) -> WorkspaceFileRead:
    directory = await _agent_dir(agent_id, session)
    return await _upload(directory, file)


@router.get("/{agent_id}/files/{filename}")
async def download_agent_file(agent_id: int, filename: str, session: SessionDep):
    directory = await _agent_dir(agent_id, session)
    path = resolve_file(directory, filename)
    return FileResponse(path, filename=path.name, content_disposition_type="inline")


@router.delete("/{agent_id}/files/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_file(agent_id: int, filename: str, session: SessionDep) -> Response:
    directory = await _agent_dir(agent_id, session)
    delete_file(directory, filename)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


_DOC_MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


@router.post("/{agent_id}/documents")
async def generate_agent_document(
    agent_id: int,
    payload: DocumentGenerateRequest,
    session: SessionDep,
):
    """生成 Word/PDF 并直接下载；文件同时保存到该 Agent 的专属工作区。"""
    directory = await _agent_dir(agent_id, session)
    try:
        data = (
            build_pdf(payload.title, payload.content, payload.author)
            if payload.format == "pdf"
            else build_docx(payload.title, payload.content, payload.author)
        )
    except Exception as exc:
        raise AppError(
            "DOCUMENT_GENERATE_FAILED",
            f"文档生成失败：{type(exc).__name__}: {exc}",
            http_status=500,
        ) from exc

    stored = save_file(directory, output_file(payload.title, payload.format), data)
    return FileResponse(
        directory / stored.name,
        media_type=_DOC_MEDIA_TYPES[payload.format],
        filename=stored.name,
    )


# ----------------------------------------------------------------------
# Skill 附件（公共资源库）
# ----------------------------------------------------------------------


@skill_router.get("/{skill_id}/attachments", response_model=list[WorkspaceFileRead])
async def list_skill_attachments(
    skill_id: int,
    session: SessionDep,
    user: CurrentUser,
) -> list[WorkspaceFileRead]:
    directory = await _skill_dir(skill_id, session, user)
    return [
        WorkspaceFileRead(name=item.name, size=item.size, updated_at=item.updated_at)
        for item in list_files(directory)
    ]


@skill_router.post(
    "/{skill_id}/attachments",
    response_model=WorkspaceFileRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_skill_attachment(
    skill_id: int,
    session: SessionDep,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> WorkspaceFileRead:
    directory = await _skill_dir(skill_id, session, user, write=True)
    return await _upload(directory, file)


@skill_router.get("/{skill_id}/attachments/{filename}")
async def download_skill_attachment(
    skill_id: int,
    filename: str,
    session: SessionDep,
    user: CurrentUser,
):
    directory = await _skill_dir(skill_id, session, user)
    path = resolve_file(directory, filename)
    return FileResponse(path, filename=path.name, content_disposition_type="inline")


@skill_router.delete(
    "/{skill_id}/attachments/{filename}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_skill_attachment(
    skill_id: int,
    filename: str,
    session: SessionDep,
    user: CurrentUser,
) -> Response:
    directory = await _skill_dir(skill_id, session, user, write=True)
    delete_file(directory, filename)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
