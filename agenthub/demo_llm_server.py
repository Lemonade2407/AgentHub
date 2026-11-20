"""Demo OpenAI-compatible LLM Server —— 本地演示用（无外部依赖）。

用于在没有真实模型 Key 的环境中跑通 Agent 链路：
- `GET  /v1/models` 供 Model API 连通性测试；
- `POST /v1/chat/completions` 模拟一次 tool_call，再返回最终答案。

启动（默认 127.0.0.1:8101）::

    python demo_llm_server.py --host 127.0.0.1 --port 8101

然后在 AgentHub 中创建一条 custom Model API：
    base_url = http://127.0.0.1:8101/v1
    api_key  = demo-key
    model    = demo-chat
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("demo_llm_server")

MODEL_ID = "demo-chat"

_GREETING_RE = re.compile(
    r"^\s*(你好|您好|hi|hello|嗨|在吗|你是谁|介绍一下你自己)[!！?？。.\s]*$",
    re.IGNORECASE,
)

# 本地演示模型无法真正理解自然语言，这里用常见城市名 + 日期正则做最小解析，
# 让“上海9月1日”这类输入可以正确调用天气工具。
_CITIES = (
    "乌鲁木齐", "呼和浩特", "石家庄", "哈尔滨", "秦皇岛", "连云港", "齐齐哈尔",
    "上海", "北京", "广州", "深圳", "天津", "重庆", "杭州", "南京", "武汉", "成都",
    "西安", "苏州", "郑州", "长沙", "青岛", "沈阳", "大连", "昆明", "长春", "拉萨",
    "三亚", "厦门", "宁波", "济南", "福州", "合肥", "南昌", "贵阳", "南宁", "海口",
    "银川", "西宁", "兰州", "太原", "无锡", "佛山", "东莞", "珠海", "烟台", "洛阳",
    "温州", "泉州", "南通", "常州", "徐州", "嘉兴", "绍兴", "金华", "惠州", "中山",
    "保定", "唐山", "邯郸", "大同", "包头", "鞍山", "抚顺", "吉林", "扬州", "镇江",
    "泰州", "盐城", "淮安", "宿迁", "芜湖", "蚌埠", "安庆", "九江", "赣州", "淄博",
    "潍坊", "临沂", "济宁", "泰安", "威海", "日照", "开封", "新乡", "南阳", "许昌",
    "宜昌", "襄阳", "荆州", "株洲", "湘潭", "衡阳", "岳阳", "常德", "桂林", "柳州",
    "北海", "遵义", "大理", "丽江", "香港", "澳门", "台北",
)
_CITY_RE = re.compile("|".join(_CITIES))
_DATE_TOKEN_RE = re.compile(
    r"\d{4}\s*[-/年]\s*\d{1,2}\s*[-/日]\s*\d{1,2}\s*日?"
    r"|\d{4}\s*[-/年]\s*\d{1,2}\s*月\s*\d{1,2}\s*日?"
    r"|\d{1,2}\s*月\s*\d{1,2}\s*日?"
)
_RANGE_SEPARATOR_RE = re.compile(r"(到|至|~|—|-|－)")


def _parse_cities(user_text: str) -> list[str]:
    """找出用户输入中的所有城市名（去重、保持出现顺序）。"""
    cities: list[str] = []
    for match in _CITY_RE.finditer(user_text or ""):
        name = match.group(0)
        if name not in cities:
            cities.append(name)
    return cities


def _date_span(user_text: str) -> tuple[str | None, str | None]:
    """解析单个日期或“9月1日到9月3日”这样的日期区间。"""
    matches = list(_DATE_TOKEN_RE.finditer(user_text or ""))
    if not matches:
        return None, None
    start = re.sub(r"\s+", "", matches[0].group(0))
    if len(matches) > 1:
        between = (user_text or "")[matches[0].end():matches[1].start()]
        if _RANGE_SEPARATOR_RE.search(between):
            return start, re.sub(r"\s+", "", matches[1].group(0))
    return start, None


def _document_arguments(properties: dict[str, Any], user_text: str) -> dict[str, Any]:
    """本地演示：把用户输入当作文档标题与正文，按是否提到 PDF 选择格式。"""
    text = (user_text or "").strip()
    title = (text.splitlines()[0] if text else "未命名文档")[:40]
    arguments: dict[str, Any] = {}
    if "title" in properties:
        arguments["title"] = title
    if "content" in properties:
        arguments["content"] = text or "（空文档）"
    if "format" in properties:
        arguments["format"] = "pdf" if "pdf" in text.lower() else "docx"
    if "author" in properties:
        arguments["author"] = "AgentHub"
    return arguments


def _weather_arguments(properties: dict[str, Any], user_text: str) -> dict[str, Any]:
    """从“北京和上海明天”“上海9月1日到9月3日”这类输入中解析参数。"""
    arguments: dict[str, Any] = {}
    if "city" in properties:
        cities = _parse_cities(user_text)
        arguments["city"] = "、".join(cities) if cities else "北京"
    if "date" in properties:
        start_date, end_date = _date_span(user_text)
        if start_date:
            arguments["date"] = start_date
        elif "今天" in user_text:
            arguments["date"] = "今天"
        elif "明天" in user_text:
            arguments["date"] = "明天"
        elif "昨天" in user_text:
            arguments["date"] = "昨天"
        if end_date and "end_date" in properties:
            arguments["end_date"] = end_date
    return arguments


def _completion(
    *,
    content: str | None,
    tool_calls: list[dict[str, Any]] | None = None,
    finish_reason: str = "stop",
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 32, "completion_tokens": 16, "total_tokens": 48},
    }


def _arguments_for(tool: dict[str, Any], user_text: str = "") -> dict[str, Any]:
    schema = (tool.get("function") or {}).get("parameters") or {}
    properties = schema.get("properties") or {}
    name = str((tool.get("function") or {}).get("name") or "")
    if "document" in name.lower() or ("title" in properties and "content" in properties):
        return _document_arguments(properties, user_text)
    if "weather" in name.lower() or "city" in properties:
        return _weather_arguments(properties, user_text)
    arguments: dict[str, Any] = {}
    for name, spec in properties.items():
        if not isinstance(spec, dict):
            arguments[name] = "demo"
            continue
        enum = spec.get("enum")
        if isinstance(enum, list) and enum:
            arguments[name] = enum[0]
            continue
        kind = spec.get("type")
        if kind == "integer":
            arguments[name] = 2 if "per" in name else 1
        elif kind == "number":
            arguments[name] = 1.0
        elif kind == "boolean":
            arguments[name] = True
        elif name in {"q", "query", "keyword", "search"}:
            arguments[name] = "AgentHub"
        elif name == "path":
            arguments[name] = "/reports/demo.csv"
        elif name == "message":
            arguments[name] = "hello from demo agent"
        else:
            arguments[name] = "demo"
    return arguments


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") in {"text", "output_text"}
        )
    return ""


def _last_message_text(messages: list[Any], role: str) -> str:
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == role:
            return _message_text(message)
    return ""


def build_completion(body: dict[str, Any]) -> dict[str, Any]:
    messages = body.get("messages") or []
    tools = body.get("tools") or []
    user_text = _last_message_text(messages, "user")
    tool_text = _last_message_text(messages, "tool")

    if tool_text:
        summary = tool_text.strip()
        if len(summary) > 1200:
            summary = summary[:1200] + "…"
        return _completion(
            content="已调用工具，结果如下：\n" + (summary or "工具执行完成。"),
            finish_reason="stop",
        )

    if _GREETING_RE.match(user_text or ""):
        return _completion(
            content=(
                "你好，我是 chat，一个本地演示助手。"
                "当前使用的是本地演示模型，可以帮你调用 MCP 工具。"
                "试试问我：“查一下最近的 issue”。"
            ),
            finish_reason="stop",
        )

    if not tools:
        return _completion(
            content=f"这是本地演示模型返回的示例回答。你刚才说的是：{user_text or '（空）'}",
            finish_reason="stop",
        )

    first = tools[0] if isinstance(tools[0], dict) else {}
    function = first.get("function") or {}
    name = str(function.get("name") or "")
    if not name:
        return _completion(content="演示完成：未发现可用工具。", finish_reason="stop")

    tool_call = {
        "id": f"call_{uuid.uuid4().hex[:12]}",
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(_arguments_for(first, user_text), ensure_ascii=False),
        },
    }
    return _completion(content=None, tool_calls=[tool_call], finish_reason="tool_calls")


class DemoLlmHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AgentHubDemoLLM/0.1"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/v1/models", "/models"}:
            self._send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": MODEL_ID,
                            "object": "model",
                            "created": int(time.time()),
                            "owned_by": "agenthub-demo",
                        }
                    ],
                },
            )
            return
        if path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in {"/v1/chat/completions", "/chat/completions"}:
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid json"})
            return
        logger.info(
            "chat.completions model=%s tools=%s messages=%s",
            body.get("model"),
            len(body.get("tools") or []),
            len(body.get("messages") or []),
        )
        self._send_json(200, build_completion(body))

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("客户端已断开")


def build_server(host: str = "127.0.0.1", port: int = 8101) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), DemoLlmHandler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentHub Demo OpenAI-compatible LLM")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8101)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")
    server = build_server(args.host, args.port)
    logger.info("Demo LLM Server 监听 http://%s:%d/v1", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
