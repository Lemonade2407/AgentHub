"""天气 MCP Server 测试：日期解析、open-meteo 查询与 MCP 端到端链路。

所有外部网络请求都通过 `WeatherService(fetch_json=...)` 注入的假函数替换，
测试不依赖真实网络。
"""

from __future__ import annotations

import threading
from datetime import date, timedelta
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

import pytest

from app.mcp.client_adapter import HttpMcpClientFactory, StreamableHttpMcpClient
from tests.mcp_fakes import make_server
from weather_mcp_server.server import (
    WeatherError,
    WeatherService,
    build_server,
    parse_cities,
    parse_date,
    weather_description,
)

TODAY = date(2026, 8, 20)


def _geocoding_payload(name: str = "上海") -> dict:
    return {
        "results": [
            {
                "name": name,
                "admin1": "上海市" if name == "上海" else "",
                "country": "中国",
                "latitude": 31.2304,
                "longitude": 121.4737,
            }
        ]
    }


def _daily_payload(*days: str, with_probability: bool = True) -> dict:
    count = len(days)
    daily = {
        "time": list(days),
        "weather_code": [2] * count,
        "temperature_2m_max": [31.2] * count,
        "temperature_2m_min": [24.8] * count,
        "precipitation_sum": [0.0] * count,
        "wind_speed_10m_max": [12.5] * count,
    }
    if with_probability:
        daily["precipitation_probability_max"] = [20] * count
    return {"daily": daily}


def _range_payload(url: str, *, with_probability: bool) -> dict:
    """按请求里的 start_date/end_date 生成覆盖整个区间的假数据。"""
    query = parse_qs(urlparse(url).query)
    start = date.fromisoformat(query["start_date"][0])
    end = date.fromisoformat(query["end_date"][0])
    days = [
        (start + timedelta(days=index)).isoformat()
        for index in range((end - start).days + 1)
    ]
    return _daily_payload(*days, with_probability=with_probability)


def _service(*, daily: dict | None = None, city_found: bool = True) -> WeatherService:
    calls: list[str] = []

    def fetch(url: str) -> dict:
        calls.append(url)
        if "geocoding" in url:
            if not city_found:
                return {"results": []}
            name = parse_qs(urlparse(url).query).get("name", ["上海"])[0]
            return _geocoding_payload(name)
        if "forecast" in url:
            return daily if daily is not None else _range_payload(url, with_probability=True)
        if "archive" in url:
            return daily if daily is not None else _range_payload(url, with_probability=False)
        raise AssertionError(f"unexpected url: {url}")

    service = WeatherService(fetch_json=fetch)
    service.calls = calls  # type: ignore[attr-defined]
    return service


def test_parse_date_supports_common_forms() -> None:
    assert parse_date("今天", today=TODAY) == TODAY
    assert parse_date(None, today=TODAY) == TODAY
    assert parse_date("明天", today=TODAY) == date(2026, 8, 21)
    assert parse_date("后天", today=TODAY) == date(2026, 8, 22)
    assert parse_date("大后天", today=TODAY) == date(2026, 8, 23)
    assert parse_date("昨天", today=TODAY) == date(2026, 8, 19)
    assert parse_date("前天", today=TODAY) == date(2026, 8, 18)
    assert parse_date("2026-09-01", today=TODAY) == date(2026, 9, 1)
    assert parse_date("2026年9月1日", today=TODAY) == date(2026, 9, 1)
    assert parse_date("9月1日", today=TODAY) == date(2026, 9, 1)
    with pytest.raises(WeatherError):
        parse_date("下周三", today=TODAY)


def test_http_get_json_retries_transient_connection_error(monkeypatch) -> None:
    import weather_mcp_server.server as server_module

    calls = {"count": 0}

    class FakeResponse:
        def read(self) -> bytes:
            return b'{"ok": true}'

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        calls["count"] += 1
        if calls["count"] == 1:
            raise URLError(TimeoutError("handshake operation timed out"))
        return FakeResponse()

    monkeypatch.setattr(server_module, "urlopen", fake_urlopen)
    monkeypatch.setattr(server_module.time, "sleep", lambda _seconds: None)

    assert server_module._http_get_json("https://example.test") == {"ok": True}
    assert calls["count"] == 2


def test_weather_description_maps_wmo_codes() -> None:
    assert weather_description(0) == "晴"
    assert weather_description(2) == "多云"
    assert weather_description(61) == "小雨"
    assert weather_description(95) == "雷阵雨"
    assert "未知天气" in weather_description(1234)


def test_query_weather_uses_forecast_for_upcoming_date() -> None:
    service = _service()
    text = service.query("上海", date(2026, 9, 1), today=TODAY)

    assert "上海，上海市，中国 2026-09-01 天气" in text
    assert "天气：多云" in text
    assert "24.8°C ~ 31.2°C" in text
    assert "概率 20%" in text
    assert "最大风速：12.5 km/h" in text
    assert "open-meteo forecast" in text
    assert "forecast" in service.calls[1]


def test_query_weather_uses_archive_for_old_date() -> None:
    service = _service()
    text = service.query("上海", date(2025, 1, 1), today=TODAY)

    assert "2025-01-01 天气" in text
    assert "open-meteo archive" in text
    assert "archive" in service.calls[1]


def test_query_weather_reports_unknown_city() -> None:
    service = _service(city_found=False)
    with pytest.raises(WeatherError, match="未找到城市"):
        service.query("不存在的城市", date(2026, 9, 1), today=TODAY)


def test_query_weather_reports_missing_day() -> None:
    service = _service(daily=_daily_payload("2026-09-02"))
    with pytest.raises(WeatherError, match="未获取到"):
        service.query("上海", date(2026, 9, 1), today=TODAY)


def test_parse_cities_supports_string_and_list() -> None:
    assert parse_cities("北京、上海") == ["北京", "上海"]
    assert parse_cities("北京,上海，广州") == ["北京", "上海", "广州"]
    assert parse_cities(["北京", "上海", "北京"]) == ["北京", "上海"]
    assert parse_cities("") == []


def test_query_multiple_cities_returns_one_block_each() -> None:
    service = _service()
    text = service.query_span("北京、上海", date(2026, 9, 1), date(2026, 9, 1), today=TODAY)

    assert "北京，中国 2026-09-01 天气" in text
    assert "上海，上海市，中国 2026-09-01 天气" in text
    assert text.count("数据来源：") == 2


def test_query_date_range_returns_each_day() -> None:
    service = _service()
    text = service.query_span("上海", date(2026, 9, 1), date(2026, 9, 3), today=TODAY)

    assert "上海，上海市，中国 2026-09-01 ~ 2026-09-03 天气" in text
    assert "2026-09-01：多云" in text
    assert "2026-09-02：多云" in text
    assert "2026-09-03：多云" in text
    assert "open-meteo forecast" in text


def test_query_range_spans_forecast_and_archive() -> None:
    service = _service()
    # 2026-05-19 距 TODAY 93 天（archive），05-20/05-21 在 92 天内（forecast）
    text = service.query_span("上海", date(2026, 5, 19), date(2026, 5, 21), today=TODAY)

    assert "2026-05-19：" in text
    assert "2026-05-20：" in text
    assert "2026-05-21：" in text
    assert "open-meteo archive" in text
    assert "open-meteo forecast" in text
    assert text.index("2026-05-19：") < text.index("2026-05-20：") < text.index("2026-05-21：")


def test_query_span_rejects_invalid_range() -> None:
    service = _service()
    with pytest.raises(WeatherError, match="不能早于"):
        service.query_span("上海", date(2026, 9, 3), date(2026, 9, 1), today=TODAY)


@pytest.fixture
def weather_endpoint():
    """在随机端口启动天气 MCP Server（注入假数据源），测试结束即关闭。"""
    server = build_server("127.0.0.1", 0, service=_service())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/mcp"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def test_mcp_tools_list_and_call(weather_endpoint: str) -> None:
    server_config = make_server(id=1, name="weather", endpoint=weather_endpoint)
    factory = HttpMcpClientFactory()
    async with StreamableHttpMcpClient(server_config) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools] == ["query_weather"]
        assert tools[0].input_schema["type"] == "object"

        result = await client.call_tool("query_weather", {"city": "上海", "date": "9月1日"})
    await factory.aclose()

    assert result.is_error is False
    assert "多云" in result.content[0]["text"]


async def test_mcp_call_without_city_returns_tool_error(weather_endpoint: str) -> None:
    server_config = make_server(id=1, name="weather", endpoint=weather_endpoint)
    async with StreamableHttpMcpClient(server_config) as client:
        result = await client.call_tool("query_weather", {})

    assert result.is_error is True
    assert "city 不能为空" in result.content[0]["text"]


async def test_mcp_multi_city_and_date_range(weather_endpoint: str) -> None:
    server_config = make_server(id=1, name="weather", endpoint=weather_endpoint)
    async with StreamableHttpMcpClient(server_config) as client:
        result = await client.call_tool(
            "query_weather",
            {"city": "北京、上海", "date": "9月1日", "end_date": "9月3日"},
        )

    assert result.is_error is False
    text = result.content[0]["text"]
    assert "北京" in text and "上海" in text
    assert f"{date.today().year}-09-02：" in text


async def test_mcp_invalid_range_returns_tool_error(weather_endpoint: str) -> None:
    server_config = make_server(id=1, name="weather", endpoint=weather_endpoint)
    async with StreamableHttpMcpClient(server_config) as client:
        result = await client.call_tool(
            "query_weather",
            {"city": "上海", "date": "9月3日", "end_date": "9月1日"},
        )

    assert result.is_error is True
    assert "不能早于" in result.content[0]["text"]
