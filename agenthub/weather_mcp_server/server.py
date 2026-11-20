"""天气 MCP Server —— 基于 open-meteo 免费 API 的只读天气查询。

对外只暴露一个 Tool：

| Tool | 说明 |
|---|---|
| `query_weather` | 入参 `city`（可多个）+ 可选 `date` / `end_date`，返回指定城市指定日期或区间的天气 |

数据源（无需 API Key）：

- Geocoding：`https://geocoding-api.open-meteo.com/v1/search`
- 天气预报 / 近 92 天：`https://api.open-meteo.com/v1/forecast`
- 更早的历史天气：`https://archive-api.open-meteo.com/v1/archive`

传输与 `demo_mcp_server` 一致：`streamable_http`，单个端点 `POST /mcp`，
JSON-RPC 2.0 报文，仅用标准库实现。

本地启动（默认 `0.0.0.0:8102`）::

    python -m weather_mcp_server --host 0.0.0.0 --port 8102

平台侧在 MCP 中心注册，`endpoint = http://127.0.0.1:8102/mcp`。
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger("weather_mcp_server")

MCP_PATH = "/mcp"
PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "agenthub-weather-mcp", "version": "0.1.0"}

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HTTP_TIMEOUT = 20.0
# open-meteo 偶发 TLS 握手超时，对连接类错误重试一次
HTTP_RETRIES = 2

# 中国时区（亚洲/上海），用于“今天/明天”的判定
CST = timezone(timedelta(hours=8))

# 天气预报可覆盖的时间窗口（open-meteo forecast 限制：过去 92 天 ~ 未来 16 天）
FORECAST_PAST_DAYS = 92
FORECAST_FUTURE_DAYS = 16

# 单次查询的保护上限：避免一次调用产生过大的输出
MAX_CITIES = 5
MAX_RANGE_DAYS = 31

# WMO Weather interpretation codes
WMO_DESCRIPTIONS: dict[int, str] = {
    0: "晴",
    1: "大部晴朗",
    2: "多云",
    3: "阴",
    45: "有雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "大毛毛雨",
    56: "冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "米雪",
    80: "小阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷阵雨",
    96: "雷阵雨伴小冰雹",
    99: "雷阵雨伴强冰雹",
}

_DATE_RE = re.compile(r"^\s*(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?\s*$")
_MONTH_DAY_RE = re.compile(r"^\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?\s*$")

FetchJson = Callable[[str], dict]


class WeatherError(Exception):
    """可预期的查询失败（城市不存在、日期越界、上游无数据等）。"""


def _http_get_json(url: str) -> dict:
    """GET 并解析 JSON；连接类错误（含 TLS 握手超时）重试一次。"""
    last_error: Exception | None = None
    for attempt in range(HTTP_RETRIES):
        request = Request(url, headers={"User-Agent": "agenthub-weather-mcp/0.1"})
        try:
            with urlopen(request, timeout=HTTP_TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError:
            raise
        except OSError as exc:  # URLError / TimeoutError 均为 OSError 子类
            last_error = exc
            if attempt + 1 < HTTP_RETRIES:
                time.sleep(0.6)
    if last_error is not None:
        raise last_error
    raise WeatherError("天气数据源请求失败")


# 相对日期偏移（天）；key 统一小写后匹配
_RELATIVE_DAYS: dict[str, int] = {
    "": 0,
    "今天": 0,
    "今日": 0,
    "today": 0,
    "明天": 1,
    "明日": 1,
    "tomorrow": 1,
    "后天": 2,
    "后日": 2,
    "大后天": 3,
    "昨天": -1,
    "昨日": -1,
    "yesterday": -1,
    "前天": -2,
}


def parse_date(value: str | None, *, today: date | None = None) -> date:
    """解析用户日期：今天/明天/后天/大后天/昨天/前天/YYYY-MM-DD/YYYY年M月D日/M月D日。"""
    today = today or datetime.now(CST).date()
    text = (value or "").strip()
    keyword = text.lower()
    if keyword in _RELATIVE_DAYS:
        return today + timedelta(days=_RELATIVE_DAYS[keyword])

    match = _DATE_RE.match(text)
    if match:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    match = _MONTH_DAY_RE.match(text)
    if match:
        return date(today.year, int(match.group(1)), int(match.group(2)))

    raise WeatherError(
        f"无法识别的日期：{value}"
        "（支持 今天/明天/后天/大后天/昨天/前天/YYYY-MM-DD/M月D日）"
    )


def parse_cities(value: Any) -> list[str]:
    """解析城市参数：支持字符串（顿号/逗号/分号/斜杠分隔）或字符串数组。"""
    if isinstance(value, (list, tuple)):
        raw = [str(item) for item in value]
    else:
        raw = re.split(r"[、,，;；/\s]+", str(value or ""))

    cities: list[str] = []
    for item in raw:
        name = item.strip()
        if name and name not in cities:
            cities.append(name)
    return cities


def weather_description(code: Any) -> str:
    """WMO 天气代码转中文描述。"""
    try:
        return WMO_DESCRIPTIONS.get(int(code), f"未知天气（代码 {code}）")
    except (TypeError, ValueError):
        return f"未知天气（代码 {code}）"


@dataclass(frozen=True)
class City:
    name: str
    admin: str
    country: str
    latitude: float
    longitude: float

    @property
    def label(self) -> str:
        parts = [self.name]
        if self.admin and self.admin != self.name:
            parts.append(self.admin)
        if self.country:
            parts.append(self.country)
        return "，".join(parts)


@dataclass(frozen=True)
class DailyWeather:
    day: date
    description: str
    temperature_min: float | None
    temperature_max: float | None
    precipitation_sum: float | None
    precipitation_probability: int | None
    wind_speed_max: float | None
    source: str


class WeatherService:
    """open-meteo 查询封装；`fetch_json` 可注入以便测试离线运行。"""

    def __init__(self, fetch_json: FetchJson = _http_get_json) -> None:
        self._fetch = fetch_json

    def resolve_city(self, city: str) -> City:
        name = (city or "").strip()
        if not name:
            raise WeatherError("city 不能为空，请提供城市名，例如：上海")
        params = urlencode({"name": name, "count": 1, "language": "zh", "format": "json"})
        payload = self._fetch(f"{GEOCODING_URL}?{params}")
        results = payload.get("results") or []
        if not results:
            raise WeatherError(f"未找到城市「{name}」，请尝试使用更完整的城市名，例如：上海、北京、乌鲁木齐")
        top = results[0]
        try:
            latitude = float(top["latitude"])
            longitude = float(top["longitude"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WeatherError(f"城市「{name}」的坐标解析失败") from exc
        return City(
            name=str(top.get("name") or name),
            admin=str(top.get("admin1") or ""),
            country=str(top.get("country") or ""),
            latitude=latitude,
            longitude=longitude,
        )

    def fetch_daily(
        self, city: City, day: date, *, today: date | None = None
    ) -> DailyWeather:
        return self.fetch_daily_range(city, day, day, today=today)[0]

    def fetch_daily_range(
        self, city: City, start: date, end: date, *, today: date | None = None
    ) -> list[DailyWeather]:
        """按日期区间取数；跨越 forecast / archive 窗口时自动分组请求。"""
        today = today or datetime.now(CST).date()
        days = [start + timedelta(days=index) for index in range((end - start).days + 1)]

        forecast_days = [
            day for day in days
            if -FORECAST_PAST_DAYS <= (day - today).days <= FORECAST_FUTURE_DAYS
        ]
        forecast_set = set(forecast_days)
        archive_days = [day for day in days if day not in forecast_set]

        found: dict[date, DailyWeather] = {}
        if forecast_days:
            found.update(
                self._fetch_range(city, min(forecast_days), max(forecast_days), source="forecast")
            )
        if archive_days:
            found.update(
                self._fetch_range(city, min(archive_days), max(archive_days), source="archive")
            )

        missing = [day for day in days if day not in found]
        if missing:
            preview = "、".join(day.isoformat() for day in missing[:3])
            raise WeatherError(f"未获取到 {city.label} 以下日期的天气数据：{preview}")
        return [found[day] for day in days]

    def _fetch_range(
        self, city: City, start: date, end: date, *, source: str
    ) -> dict[date, DailyWeather]:
        daily_fields = [
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "wind_speed_10m_max",
        ]
        if source == "forecast":
            daily_fields.insert(4, "precipitation_probability_max")
            url = FORECAST_URL
            label = "open-meteo forecast"
        else:
            url = ARCHIVE_URL
            label = "open-meteo archive"

        params = urlencode(
            {
                "latitude": city.latitude,
                "longitude": city.longitude,
                "daily": ",".join(daily_fields),
                "timezone": "Asia/Shanghai",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            }
        )
        payload = self._fetch(f"{url}?{params}")

        daily = payload.get("daily") or {}
        times = daily.get("time") or []
        result: dict[date, DailyWeather] = {}
        for index, time_text in enumerate(times):
            try:
                day = date.fromisoformat(str(time_text))
            except ValueError:
                continue

            def _value(field: str, index: int = index) -> Any:
                values = daily.get(field) or []
                return values[index] if index < len(values) else None

            result[day] = DailyWeather(
                day=day,
                description=weather_description(_value("weather_code")),
                temperature_min=_as_float(_value("temperature_2m_min")),
                temperature_max=_as_float(_value("temperature_2m_max")),
                precipitation_sum=_as_float(_value("precipitation_sum")),
                precipitation_probability=_as_int(_value("precipitation_probability_max")),
                wind_speed_max=_as_float(_value("wind_speed_10m_max")),
                source=label,
            )
        return result

    def query(self, city_name: str, day: date, *, today: date | None = None) -> str:
        return self.query_span(city_name, day, day, today=today)

    def query_span(
        self, city_value: Any, start: date, end: date, *, today: date | None = None
    ) -> str:
        """查询一个或多个城市在 [start, end] 区间内的天气。"""
        cities = parse_cities(city_value)
        if not cities:
            raise WeatherError("city 不能为空，请提供城市名，例如：上海")
        if len(cities) > MAX_CITIES:
            raise WeatherError(f"一次最多查询 {MAX_CITIES} 个城市，当前为 {len(cities)} 个")
        if end < start:
            raise WeatherError("end_date 不能早于 date")
        if (end - start).days + 1 > MAX_RANGE_DAYS:
            raise WeatherError(f"单次查询的日期跨度不能超过 {MAX_RANGE_DAYS} 天")

        blocks = []
        for name in cities:
            city = self.resolve_city(name)
            daily = self.fetch_daily_range(city, start, end, today=today)
            blocks.append(_format_city(city, daily))
        return "\n\n".join(blocks)


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_range(low: float | None, high: float | None) -> str:
    if low is None and high is None:
        return "暂无数据"
    if low is None:
        return f"最高 {high:.1f}°C"
    if high is None:
        return f"最低 {low:.1f}°C"
    return f"{low:.1f}°C ~ {high:.1f}°C"


def _format_city(city: City, daily: list[DailyWeather]) -> str:
    if len(daily) == 1:
        item = daily[0]
        lines = [
            f"{city.label} {item.day.isoformat()} 天气",
            f"天气：{item.description}",
            f"气温：{_format_range(item.temperature_min, item.temperature_max)}",
        ]
        if item.precipitation_sum is not None:
            precipitation = f"降水：{item.precipitation_sum:.1f} mm"
            if item.precipitation_probability is not None:
                precipitation += f"（概率 {item.precipitation_probability}%）"
            lines.append(precipitation)
        if item.wind_speed_max is not None:
            lines.append(f"最大风速：{item.wind_speed_max:.1f} km/h")
        lines.append(f"数据来源：{item.source}")
        return "\n".join(lines)

    lines = [f"{city.label} {daily[0].day.isoformat()} ~ {daily[-1].day.isoformat()} 天气"]
    lines.extend(_format_day_line(item) for item in daily)
    sources = "、".join(dict.fromkeys(item.source for item in daily))
    lines.append(f"数据来源：{sources}")
    return "\n".join(lines)


def _format_day_line(item: DailyWeather) -> str:
    parts = [item.description, _format_range(item.temperature_min, item.temperature_max)]
    if item.precipitation_sum is not None:
        precipitation = f"降水 {item.precipitation_sum:.1f} mm"
        if item.precipitation_probability is not None:
            precipitation += f"（{item.precipitation_probability}%）"
        parts.append(precipitation)
    if item.wind_speed_max is not None:
        parts.append(f"风 {item.wind_speed_max:.1f} km/h")
    return f"{item.day.isoformat()}：" + "，".join(parts)


def _text(content: str) -> list[dict]:
    return [{"type": "text", "text": content}]


def _query_weather(service: WeatherService, arguments: dict) -> tuple[list[dict], bool]:
    date_value = arguments.get("date")
    end_value = arguments.get("end_date")
    try:
        start = parse_date(str(date_value) if date_value not in (None, "") else None)
        end = parse_date(str(end_value)) if end_value not in (None, "") else start
        return _text(service.query_span(arguments.get("city"), start, end)), False
    except WeatherError as exc:
        return _text(str(exc)), True
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return _text(f"天气数据源请求失败：{type(exc).__name__}: {exc}"), True


def list_tool_schemas() -> list[dict]:
    """`tools/list` 的返回体。"""
    return [
        {
            "name": "query_weather",
            "description": (
                "查询一个或多个城市在指定日期/日期区间的天气（支持中国及全球城市）。"
                "单城市单日：city=“上海”, date=“9月1日”；"
                "多城市：city=“北京、上海”；"
                "日期区间：date=“9月1日”, end_date=“9月3日”。"
                "date/end_date 支持 今天/明天/后天/大后天/昨天/前天/YYYY-MM-DD/M月D日，"
                "date 缺省为今天。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名，可用顿号/逗号分隔多个（最多 5 个），例如：上海、北京",
                    },
                    "date": {
                        "type": "string",
                        "description": (
                            "起始日期：今天/明天/后天/大后天/昨天/前天/YYYY-MM-DD/M月D日，"
                            "默认今天"
                        ),
                    },
                    "end_date": {
                        "type": "string",
                        "description": "结束日期（含），不填则只查 date 当天；与 date 跨度最多 31 天",
                    },
                },
                "required": ["city"],
            },
        }
    ]


def dispatch(message: dict, service: WeatherService) -> dict | None:
    """处理一条 JSON-RPC 消息；通知返回 None（不应答）。"""
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
        return _call_tool(request_id, message.get("params") or {}, service)
    return _error(request_id, -32601, f"未实现的方法：{method}")


def _call_tool(request_id: Any, params: dict, service: WeatherService) -> dict:
    name = str(params.get("name") or "")
    arguments = params.get("arguments") or {}
    if name != "query_weather":
        return _error(request_id, -32602, f"未知 Tool：{name}")
    content, is_error = _query_weather(service, dict(arguments))
    return _result(request_id, {"content": content, "isError": is_error})


def _result(request_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class McpRequestHandler(BaseHTTPRequestHandler):
    """单个 `POST /mcp` 端点的 Streamable HTTP 处理器。"""

    protocol_version = "HTTP/1.1"
    server_version = "AgentHubWeatherMCPServer/0.1"

    def do_POST(self) -> None:  # noqa: N802（BaseHTTPRequestHandler 约定）
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

        response = dispatch(message, self.server.weather_service)  # type: ignore[attr-defined]
        if response is None:  # 通知不应答
            self._send_empty(202)
            return

        extra_headers = None
        if message.get("method") == "initialize":
            extra_headers = {"Mcp-Session-Id": self.server.session_id}  # type: ignore[attr-defined]
        self._send_json(200, response, extra_headers)

    def do_GET(self) -> None:  # noqa: N802
        self._send_empty(405, extra_headers={"Allow": "POST"})

    def do_DELETE(self) -> None:  # noqa: N802（会话终止；本 Server 无状态，直接 204）
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


def build_server(
    host: str = "127.0.0.1",
    port: int = 8102,
    service: WeatherService | None = None,
) -> ThreadingHTTPServer:
    """创建（但不启动）天气 MCP Server，供 `main()` 与测试复用。"""
    server = ThreadingHTTPServer((host, port), McpRequestHandler)
    server.session_id = uuid.uuid4().hex  # type: ignore[attr-defined]
    server.weather_service = service or WeatherService()  # type: ignore[attr-defined]
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentHub 天气 MCP Server（streamable_http）")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8102)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")
    server = build_server(args.host, args.port)
    logger.info("Weather MCP Server 监听 http://%s:%d%s", args.host, args.port, MCP_PATH)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("收到中断，正在关闭")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
