"""文档生成 MCP Server：生成 Word(.docx) / PDF 并写入 Agent 专属工作区。"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlparse
from xml.sax.saxutils import escape

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.services.workspace_service import (
    ensure_agent_dir,
    ensure_dir,
    safe_filename,
    save_file,
    workspace_root,
)

logger = logging.getLogger("document_mcp_server")

MCP_PATH = "/mcp"
PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "agenthub-document-mcp", "version": "0.1.0"}
CST = timezone(timedelta(hours=8))

_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")
_NUMBER_RE = re.compile(r"^\s*\d+[.、]\s+(.*)$")

try:  # reportlab 内置中文 CID 字体，无需额外字体文件
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
except Exception:  # pragma: no cover - 重复注册时忽略
    logger.debug("STSong-Light 已注册或不可用", exc_info=True)


def _blocks(content: str) -> list[tuple[str, str]]:
    """把内容解析为标题 / 段落 / 列表等块。"""
    result: list[tuple[str, str]] = []
    for raw in content.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("### "):
            result.append(("h3", line[4:].strip()))
        elif line.startswith("## "):
            result.append(("h2", line[3:].strip()))
        elif line.startswith("# "):
            result.append(("h1", line[2:].strip()))
        elif match := _BULLET_RE.match(line):
            result.append(("bullet", match.group(1).strip()))
        elif match := _NUMBER_RE.match(line):
            result.append(("number", match.group(1).strip()))
        else:
            result.append(("p", line.strip()))
    return result


def _set_east_asia_font(style, font_name: str) -> None:
    style.font.name = font_name
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), font_name)


def _set_run_font(run, font_name: str, size_pt: float, *, bold: bool) -> None:
    """同时设置 ascii / hAnsi / eastAsia，确保中文字体真正生效。"""
    run.font.name = font_name
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run.font.color.rgb = RGBColor(0, 0, 0)

    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), font_name)
    rfonts.set(qn("w:hAnsi"), font_name)
    rfonts.set(qn("w:eastAsia"), font_name)


def _set_first_line_indent(
    paragraph, *, chars: int = 2, font_size_pt: float = 12
) -> None:
    """首行缩进 N 个字符（firstLineChars 为百分之一字符）。"""
    ppr = paragraph._p.get_or_add_pPr()
    indent = ppr.find(qn("w:ind"))
    if indent is None:
        indent = OxmlElement("w:ind")
        ppr.append(indent)
    indent.set(qn("w:firstLineChars"), str(chars * 100))
    # 部分 Word 版本不识别 firstLineChars，用 twips 提供等价兜底
    indent.set(qn("w:firstLine"), str(int(chars * font_size_pt * 20)))


def build_docx(title: str, content: str, author: str = "") -> bytes:
    document = Document()
    for section in document.sections:
        section.top_margin = Cm(2.4)
        section.bottom_margin = Cm(2.4)
        section.left_margin = Cm(2.6)
        section.right_margin = Cm(2.6)

    normal = document.styles["Normal"]
    _set_east_asia_font(normal, "宋体")
    normal.font.size = Pt(12)

    # 封面页：标题 + 作者/日期，随后分页进入正文
    title_paragraph = document.add_paragraph()
    title_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_paragraph.paragraph_format.space_before = Pt(180)
    title_paragraph.paragraph_format.space_after = Pt(24)
    _set_run_font(title_paragraph.add_run(title), "黑体", 22, bold=True)

    meta_bits = [bit for bit in (author, datetime.now(CST).strftime("%Y-%m-%d")) if bit]
    if meta_bits:
        meta = document.add_paragraph()
        meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
        meta.paragraph_format.space_after = Pt(6)
        meta_run = meta.add_run(" · ".join(meta_bits))
        _set_run_font(meta_run, "宋体", 11, bold=False)
        meta_run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

    document.add_page_break()

    for kind, text in _blocks(content):
        if kind in {"h1", "h2", "h3"}:
            level = {"h1": 1, "h2": 2, "h3": 3}[kind]
            paragraph = document.add_paragraph(style=f"Heading {level}")
            paragraph.paragraph_format.space_before = Pt(8)
            paragraph.paragraph_format.space_after = Pt(4)
            run = paragraph.add_run(text)
            if kind == "h1":
                # # 一级标题：黑体 / 小五(9pt) / 加粗
                _set_run_font(run, "黑体", 9, bold=True)
            elif kind == "h2":
                # ## 二级标题：宋体 / 四号(14pt) / 加粗
                _set_run_font(run, "宋体", 14, bold=True)
            else:
                # ### 未在规范中定义，按宋体 / 小四(12pt) / 加粗处理
                _set_run_font(run, "宋体", 12, bold=True)
        elif kind == "bullet":
            paragraph = document.add_paragraph(style="List Bullet")
            _set_run_font(paragraph.add_run(text), "宋体", 12, bold=False)
        elif kind == "number":
            paragraph = document.add_paragraph(style="List Number")
            _set_run_font(paragraph.add_run(text), "宋体", 12, bold=False)
        else:
            # 普通正文：宋体 / 小四(12pt) / 常规 / 首行缩进 2 字符
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.line_spacing = 1.5
            paragraph.paragraph_format.space_after = Pt(6)
            _set_run_font(paragraph.add_run(text), "宋体", 12, bold=False)
            _set_first_line_indent(paragraph, chars=2, font_size_pt=12)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def build_pdf(title: str, content: str, author: str = "") -> bytes:
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2.4 * cm,
        rightMargin=2.4 * cm,
        topMargin=2.4 * cm,
        bottomMargin=2.2 * cm,
        title=title,
        author=author or "AgentHub",
    )

    body = ParagraphStyle(
        "BodyCN",
        fontName="STSong-Light",
        fontSize=10.5,
        leading=18,
        textColor=colors.HexColor("#222222"),
        spaceAfter=6,
    )
    title_style = ParagraphStyle(
        "TitleCN",
        parent=body,
        fontSize=22,
        leading=30,
        alignment=1,
        spaceAfter=10,
    )
    meta_style = ParagraphStyle(
        "MetaCN",
        parent=body,
        fontSize=9,
        textColor=colors.HexColor("#888888"),
        alignment=1,
        spaceAfter=18,
    )
    heading_styles = {
        "h1": ParagraphStyle("H1CN", parent=body, fontSize=15, leading=24, spaceBefore=12),
        "h2": ParagraphStyle("H2CN", parent=body, fontSize=13, leading=22, spaceBefore=10),
        "h3": ParagraphStyle("H3CN", parent=body, fontSize=11.5, leading=20, spaceBefore=8),
    }
    bullet_style = ParagraphStyle("BulletCN", parent=body, leftIndent=14, bulletIndent=4)

    story: list[Any] = [Paragraph(escape(title), title_style)]
    meta_bits = [bit for bit in (author, datetime.now(CST).strftime("%Y-%m-%d")) if bit]
    if meta_bits:
        story.append(Paragraph(escape(" · ".join(meta_bits)), meta_style))

    for kind, text in _blocks(content):
        if kind in heading_styles:
            story.append(Paragraph(escape(text), heading_styles[kind]))
        elif kind == "bullet":
            story.append(Paragraph(f"• {escape(text)}", bullet_style))
        elif kind == "number":
            story.append(Paragraph(escape(text), bullet_style))
        else:
            story.append(Paragraph(escape(text), body))

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("STSong-Light", 8)
        canvas.setFillColor(colors.HexColor("#999999"))
        canvas.drawCentredString(A4[0] / 2, 1.2 * cm, f"第 {doc.page} 页")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def output_file(title: str, extension: str) -> str:
    base = safe_filename(title)[:60] or "document"
    stamp = datetime.now(CST).strftime("%Y%m%d-%H%M%S")
    return f"{base}-{stamp}-{uuid.uuid4().hex[:4]}.{extension}"


def _target(meta: dict | None) -> tuple[Any, str | None]:
    agent_id = (meta or {}).get("agent_id")
    try:
        numeric = int(agent_id) if agent_id is not None else None
    except (TypeError, ValueError):
        numeric = None
    if numeric is not None and numeric > 0:
        return ensure_agent_dir(numeric), f"/api/agents/{numeric}/files"
    return ensure_dir(workspace_root() / "generated"), None


def _metadata_path(agent_id: int, filename: str):
    return workspace_root() / ".meta" / f"agent-{agent_id}" / f"{safe_filename(filename)}.json"


def _save_metadata(agent_id: int, filename: str, payload: dict) -> None:
    path = _metadata_path(agent_id, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _load_metadata(agent_id: int, filename: str) -> dict | None:
    path = _metadata_path(agent_id, filename)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def generate_document(arguments: dict, meta: dict | None) -> tuple[list[dict], bool]:
    title = str(arguments.get("title") or "").strip()
    content = str(arguments.get("content") or "").strip()
    fmt = str(arguments.get("format") or "docx").lower()
    author = str(arguments.get("author") or "").strip()
    source_name = str(arguments.get("source_name") or "").strip()

    agent_id = None
    try:
        raw_agent_id = (meta or {}).get("agent_id")
        agent_id = int(raw_agent_id) if raw_agent_id is not None else None
    except (TypeError, ValueError):
        agent_id = None

    # 格式转换：复用上一轮文档的原始 Markdown，而不是让模型重新编写正文
    if source_name:
        if agent_id is None:
            return _text("source_name 仅在 Agent 工作区内可用"), True
        source_meta = _load_metadata(agent_id, source_name)
        if source_meta is None:
            return _text(f"未找到可转换的源文档：{source_name}"), True
        title = str(source_meta.get("title") or title or Path(source_name).stem)
        content = str(source_meta.get("content") or "").strip()
        author = str(source_meta.get("author") or author)

    if not title:
        return _text("title 不能为空"), True
    if not content:
        return _text("content 不能为空"), True
    if fmt not in {"docx", "pdf"}:
        return _text(f"不支持的格式：{fmt}（可选 docx / pdf）"), True

    try:
        data = build_pdf(title, content, author) if fmt == "pdf" else build_docx(title, content, author)
    except Exception as exc:  # pragma: no cover - 生成失败转工具错误
        logger.exception("生成文档失败")
        return _text(f"生成文档失败：{type(exc).__name__}: {exc}"), True

    directory, url_base = _target(meta)
    stored = save_file(directory, output_file(title, fmt), data)
    if agent_id is not None:
        _save_metadata(
            agent_id,
            stored.name,
            {"title": title, "content": content, "author": author},
        )

    lines = [
        f"已生成 {fmt.upper()} 文档：{stored.name}",
        f"大小：{stored.size / 1024:.1f} KB",
    ]
    if url_base:
        lines.append(f"下载/预览：{url_base}/{quote(stored.name)}")
        lines.append("文件已保存到当前 Agent 的专属工作区。")
    else:
        lines.append("未关联 Agent，文件保存在服务器 workspaces/generated 目录。")
    return _text("\n".join(lines)), False


def _text(content: str) -> list[dict]:
    return [{"type": "text", "text": content}]


ToolHandler = Callable[[dict, dict | None], tuple[list[dict], bool]]

TOOLS: dict[str, tuple[str, dict, ToolHandler]] = {
    "generate_document": (
        "生成 Word(.docx) 或 PDF 文档，并保存到当前 Agent 的专属工作区。"
        "content 支持简单 Markdown：# 一级标题、## 二级标题、- 列表项。",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "文档标题"},
                "content": {
                    "type": "string",
                    "description": "正文；支持 # / ## / ### 标题与 - 列表",
                },
                "format": {
                    "type": "string",
                    "enum": ["docx", "pdf"],
                    "description": "输出格式，默认 docx",
                },
                "author": {"type": "string", "description": "作者（可选）"},
                "source_name": {
                    "type": "string",
                    "description": (
                        "复用当前 Agent 工作区中已有文档的正文（传文件名）。"
                        "当用户要求把上一轮的 Word 改为 PDF（或反之）时使用。"
                    ),
                },
            },
            "required": [],
        },
        generate_document,
    )
}


def list_tool_schemas() -> list[dict]:
    return [
        {"name": name, "description": description, "inputSchema": schema}
        for name, (description, schema, _) in TOOLS.items()
    ]


def dispatch(message: dict) -> dict | None:
    method = message.get("method")
    request_id = message.get("id")

    if method == "notifications/initialized" or (
        request_id is None and isinstance(method, str) and method.startswith("notifications/")
    ):
        return None
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        )
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": list_tool_schemas()})
    if method == "tools/call":
        return _call_tool(request_id, message.get("params") or {})
    return _error(request_id, -32601, f"未实现的方法：{method}")


def _call_tool(request_id: Any, params: dict) -> dict:
    name = str(params.get("name") or "")
    tool = TOOLS.get(name)
    if tool is None:
        return _error(request_id, -32602, f"未知 Tool：{name}")
    arguments = params.get("arguments") or {}
    meta = params.get("_meta") or {}
    content, is_error = tool[2](dict(arguments), dict(meta))
    return _result(request_id, {"content": content, "isError": is_error})


def _result(request_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class McpRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AgentHubDocumentMCPServer/0.1"

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != MCP_PATH:
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            message = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send_json(200, _error(None, -32700, "请求体不是合法 JSON"))
            return

        response = dispatch(message)
        if response is None:
            self._send_empty(202)
            return

        extra_headers = None
        if message.get("method") == "initialize":
            extra_headers = {"Mcp-Session-Id": self.server.session_id}  # type: ignore[attr-defined]
        self._send_json(200, response, extra_headers)

    def do_GET(self) -> None:  # noqa: N802
        self._send_empty(405, extra_headers={"Allow": "POST"})

    def do_DELETE(self) -> None:  # noqa: N802
        self._send_empty(204)

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug("%s - %s", self.address_string(), fmt % args)

    def _send_json(
        self, status: int, payload: dict, extra_headers: dict[str, str] | None = None
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._write(status, body, {"Content-Type": "application/json; charset=utf-8"}, extra_headers)

    def _send_empty(self, status: int, extra_headers: dict[str, str] | None = None) -> None:
        self._write(status, b"", {}, extra_headers)

    def _write(
        self,
        status: int,
        body: bytes,
        base_headers: dict[str, str],
        extra_headers: dict[str, str] | None,
    ) -> None:
        self.send_response(status)
        for key, value in {**base_headers, **(extra_headers or {})}.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                logger.debug("客户端已断开，丢弃响应")


def build_server(host: str = "127.0.0.1", port: int = 8103) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), McpRequestHandler)
    server.session_id = uuid.uuid4().hex  # type: ignore[attr-defined]
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentHub 文档生成 MCP Server（streamable_http）")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8103)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")
    server = build_server(args.host, args.port)
    logger.info("Document MCP Server 监听 http://%s:%d%s", args.host, args.port, MCP_PATH)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("收到中断，正在关闭")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
