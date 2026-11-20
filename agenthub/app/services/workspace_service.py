"""Agent / Skill 工作区：实体目录与文件读写。

目录约定（可通过 `WORKSPACE_ROOT` 覆盖根目录）::

    workspaces/
      agents/agent-<id>/
      skills/skill-<id>/

文件元数据直接来自文件系统，不额外建表；所有文件名都经过清洗，
并校验最终路径仍位于目标目录内，防止路径穿越。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import AppError

_DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "workspaces"
_UNSAFE_CHARS = re.compile(r"[^\w\u4e00-\u9fa5.\-()（） ]+", re.UNICODE)
_MAX_NAME_LENGTH = 120


@dataclass(frozen=True)
class StoredFile:
    name: str
    size: int
    updated_at: datetime


def workspace_root() -> Path:
    configured = get_settings().workspace_root.strip()
    return Path(configured).expanduser() if configured else _DEFAULT_ROOT


def agent_dir(agent_id: int) -> Path:
    return workspace_root() / "agents" / f"agent-{agent_id}"


def skill_dir(skill_id: int) -> Path:
    return workspace_root() / "skills" / f"skill-{skill_id}"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_agent_dir(agent_id: int) -> Path:
    return ensure_dir(agent_dir(agent_id))


def ensure_skill_dir(skill_id: int) -> Path:
    return ensure_dir(skill_dir(skill_id))


def safe_filename(name: str) -> str:
    """只保留文件名本身，并清洗危险字符。"""
    base = Path(name or "").name.strip()
    if not base or base in {".", ".."}:
        raise AppError("INVALID_FILE_NAME", "文件名不能为空", http_status=400)
    cleaned = _UNSAFE_CHARS.sub("_", base).strip(" .")
    if not cleaned:
        raise AppError("INVALID_FILE_NAME", f"文件名不合法：{name}", http_status=400)
    return cleaned[:_MAX_NAME_LENGTH]


def list_files(directory: Path) -> list[StoredFile]:
    ensure_dir(directory)
    items: list[StoredFile] = []
    for entry in directory.iterdir():
        if not entry.is_file() or entry.name.endswith(".uploading"):
            continue
        stat = entry.stat()
        items.append(
            StoredFile(
                name=entry.name,
                size=stat.st_size,
                updated_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            )
        )
    return sorted(items, key=lambda item: item.updated_at, reverse=True)


def resolve_file(directory: Path, name: str) -> Path:
    filename = safe_filename(name)
    base = directory.resolve()
    path = (base / filename).resolve()
    if base not in path.parents and path != base:
        raise AppError("INVALID_FILE_NAME", "文件路径不合法", http_status=400)
    if not path.is_file():
        raise AppError("WORKSPACE_FILE_NOT_FOUND", f"文件不存在：{filename}", http_status=404)
    return path


def save_file(directory: Path, name: str, data: bytes) -> StoredFile:
    limit = get_settings().max_upload_bytes
    if len(data) > limit:
        raise AppError(
            "WORKSPACE_FILE_TOO_LARGE",
            f"文件超过上限（{limit // (1024 * 1024)} MB）",
            http_status=413,
        )

    filename = safe_filename(name)
    ensure_dir(directory)
    target = directory / filename
    temp = directory / f".{filename}.uploading"
    temp.write_bytes(data)
    temp.replace(target)

    stat = target.stat()
    return StoredFile(
        name=filename,
        size=stat.st_size,
        updated_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
    )


def delete_file(directory: Path, name: str) -> None:
    path = resolve_file(directory, name)
    path.unlink()
