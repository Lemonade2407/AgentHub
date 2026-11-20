"""文档生成 MCP Server 测试。"""

from __future__ import annotations

import io
import threading
import zipfile
from pathlib import Path

import pytest
from docx import Document

from app.core.config import get_settings
from app.mcp.client_adapter import HttpMcpClientFactory, StreamableHttpMcpClient
from document_mcp_server.server import (
    build_docx,
    build_pdf,
    build_server,
    generate_document,
    list_tool_schemas,
)
from tests.mcp_fakes import make_server

CONTENT = "# 项目周报\n\n## 本周进展\n\n- 完成文档生成能力\n- 补充 PDF 预览\n\n普通段落内容。"


def test_build_docx_and_pdf() -> None:
    docx_bytes = build_docx("测试文档", CONTENT, "AgentHub")
    pdf_bytes = build_pdf("测试文档", CONTENT, "AgentHub")

    assert docx_bytes[:2] == b"PK"
    assert len(docx_bytes) > 1000
    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 1000


def test_docx_applies_markdown_font_rules() -> None:
    data = build_docx("文档标题", "# 一级标题\n## 二级标题\n这是正文段落。")

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")

    # 中文字体必须写入 eastAsia
    assert 'w:eastAsia="黑体"' in xml
    assert 'w:eastAsia="宋体"' in xml
    # 9pt / 14pt / 12pt 对应 half-points 18 / 28 / 24
    assert 'w:sz w:val="18"' in xml
    assert 'w:sz w:val="28"' in xml
    assert 'w:sz w:val="24"' in xml
    # 首行缩进 2 字符
    assert 'w:firstLineChars="200"' in xml
    assert 'w:firstLine="480"' in xml

    document = Document(io.BytesIO(data))
    paragraphs = {p.text: p for p in document.paragraphs if p.text}

    h1 = paragraphs["一级标题"].runs[0]
    h2 = paragraphs["二级标题"].runs[0]
    body_paragraph = paragraphs["这是正文段落。"]
    body = body_paragraph.runs[0]

    assert (h1.font.name, h1.font.size.pt, h1.bold) == ("黑体", 9, True)
    assert (h2.font.name, h2.font.size.pt, h2.bold) == ("宋体", 14, True)
    assert (body.font.name, body.font.size.pt, body.bold) == ("宋体", 12, False)
    assert body_paragraph.paragraph_format.first_line_indent.pt == 24


def test_docx_inserts_cover_page() -> None:
    data = build_docx("封面标题", "# 正文一级标题\n正文内容。", "作者A")

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert 'w:br w:type="page"' in xml

    document = Document(io.BytesIO(data))
    paragraphs = document.paragraphs
    assert paragraphs[0].text == "封面标题"
    assert paragraphs[0].runs[0].font.name == "黑体"
    assert paragraphs[0].runs[0].font.size.pt == 22
    assert paragraphs[0].runs[0].bold is True
    assert paragraphs[1].text.startswith("作者A · ")

    texts = [p.text for p in paragraphs]
    assert "正文一级标题" in texts
    assert texts.index("正文一级标题") > texts.index("封面标题")


def test_tool_schema() -> None:
    schemas = list_tool_schemas()
    assert [item["name"] for item in schemas] == ["generate_document"]
    assert schemas[0]["inputSchema"]["required"] == []
    assert "source_name" in schemas[0]["inputSchema"]["properties"]


def test_generate_document_writes_agent_workspace(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    try:
        content, is_error = generate_document(
            {"title": "测试 PDF", "content": CONTENT, "format": "pdf"},
            {"agent_id": 99},
        )
        assert is_error is False
        assert "已生成 PDF" in content[0]["text"]

        files = list((tmp_path / "agents" / "agent-99").iterdir())
        assert len(files) == 1
        assert files[0].suffix == ".pdf"
        assert files[0].read_bytes()[:4] == b"%PDF"
    finally:
        monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
        get_settings.cache_clear()


def test_generate_document_requires_title_and_content() -> None:
    content, is_error = generate_document({"content": "x"}, None)
    assert is_error is True
    assert "title 不能为空" in content[0]["text"]

    content, is_error = generate_document({"title": "x"}, None)
    assert is_error is True
    assert "content 不能为空" in content[0]["text"]


def test_convert_document_by_source_name(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    try:
        _, is_error = generate_document(
            {"title": "转换源文档", "content": "# 章节\n正文内容。", "format": "docx"},
            {"agent_id": 77},
        )
        assert is_error is False
        folder = tmp_path / "agents" / "agent-77"
        source = next(folder.glob("*.docx"))

        content, is_error = generate_document(
            {"source_name": source.name, "format": "pdf"},
            {"agent_id": 77},
        )
        assert is_error is False
        assert "已生成 PDF" in content[0]["text"]
        pdfs = list(folder.glob("*.pdf"))
        assert len(pdfs) == 1
        assert pdfs[0].read_bytes()[:4] == b"%PDF"
    finally:
        monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
        get_settings.cache_clear()


@pytest.fixture
def document_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    server = build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/mcp", tmp_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
        get_settings.cache_clear()


async def test_mcp_call_generates_docx_in_workspace(document_endpoint) -> None:
    endpoint, root = document_endpoint
    config = make_server(id=2, name="document", endpoint=endpoint)
    factory = HttpMcpClientFactory()
    async with StreamableHttpMcpClient(config) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools] == ["generate_document"]

        result = await client.call_tool(
            "generate_document",
            {"title": "MCP 文档", "content": CONTENT, "format": "docx"},
            meta={"agent_id": 42, "run_id": "r_test"},
        )
    await factory.aclose()

    assert result.is_error is False
    assert "已生成 DOCX" in result.content[0]["text"]
    files = list((root / "agents" / "agent-42").iterdir())
    assert len(files) == 1
    assert files[0].suffix == ".docx"
