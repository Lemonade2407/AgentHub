"""Demo LLM 的天气参数解析测试（本地演示模型没有真模型能力，靠正则解析）。"""

from __future__ import annotations

import json

from demo_llm_server import build_completion

WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "weather_mcp.query_weather",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "date": {"type": "string"},
                "end_date": {"type": "string"},
            },
        },
    },
}


def _weather_arguments(user_text: str) -> dict:
    body = {"messages": [{"role": "user", "content": user_text}], "tools": [WEATHER_TOOL]}
    message = build_completion(body)["choices"][0]["message"]
    tool_calls = message.get("tool_calls") or []
    assert tool_calls and tool_calls[0]["function"]["name"] == "weather_mcp.query_weather"
    return json.loads(tool_calls[0]["function"]["arguments"])


def test_single_city_and_date() -> None:
    assert _weather_arguments("上海9月1日") == {"city": "上海", "date": "9月1日"}


def test_multiple_cities() -> None:
    arguments = _weather_arguments("北京和上海明天")
    assert arguments["city"] == "北京、上海"
    assert arguments["date"] == "明天"


def test_date_range() -> None:
    assert _weather_arguments("上海9月1日到9月3日") == {
        "city": "上海",
        "date": "9月1日",
        "end_date": "9月3日",
    }
