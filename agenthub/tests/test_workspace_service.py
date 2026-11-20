"""Agent / Skill 工作区文件服务测试。"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.workspace_service import (
    delete_file,
    list_files,
    resolve_file,
    safe_filename,
    save_file,
)


def test_safe_filename_strips_directories_and_unsafe_chars() -> None:
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("报告 2026.pdf") == "报告 2026.pdf"
    assert safe_filename("a<b>c.txt") == "a_b_c.txt"
    with pytest.raises(AppError) as exc:
        safe_filename("..")
    assert exc.value.code == "INVALID_FILE_NAME"


def test_save_list_and_delete(tmp_path) -> None:
    stored = save_file(tmp_path, "hello.txt", b"abc")
    assert stored.name == "hello.txt"
    assert stored.size == 3

    items = list_files(tmp_path)
    assert [item.name for item in items] == ["hello.txt"]

    delete_file(tmp_path, "hello.txt")
    assert list_files(tmp_path) == []


def test_save_overwrites_existing_file(tmp_path) -> None:
    save_file(tmp_path, "a.txt", b"old")
    stored = save_file(tmp_path, "a.txt", b"new-content")
    assert stored.size == len(b"new-content")
    assert [item.name for item in list_files(tmp_path)] == ["a.txt"]


def test_resolve_rejects_missing_file(tmp_path) -> None:
    with pytest.raises(AppError) as exc:
        resolve_file(tmp_path, "../hidden.txt")
    assert exc.value.code == "WORKSPACE_FILE_NOT_FOUND"


def test_upload_size_limit(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "4")
    get_settings.cache_clear()
    try:
        with pytest.raises(AppError) as exc:
            save_file(tmp_path, "big.bin", b"12345")
        assert exc.value.code == "WORKSPACE_FILE_TOO_LARGE"
    finally:
        monkeypatch.delenv("MAX_UPLOAD_BYTES", raising=False)
        get_settings.cache_clear()
