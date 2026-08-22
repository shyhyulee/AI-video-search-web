"""translation.py 的查詢翻譯與成本計算測試：mock OpenAI client，不呼叫真實 API。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ai_video_search_web.pipeline import translation


def _fake_response(chinese: str, english: str, prompt_tokens: int, completion_tokens: int):
    parsed = SimpleNamespace(chinese=chinese, english=english)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def test_translate_query_computes_cost_from_usage():
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(
        "你好", "hello", prompt_tokens=300, completion_tokens=20,
    )

    result = translation.translate_query(client, "hello")

    assert result.chinese == "你好"
    assert result.english == "hello"
    expected_cost = 300 * translation.PRICE_INPUT_PER_TOKEN_USD + 20 * translation.PRICE_OUTPUT_PER_TOKEN_USD
    assert result.cost_usd == pytest.approx(expected_cost)


def test_translate_query_missing_usage_returns_zero_cost():
    client = MagicMock()
    response = _fake_response("你好", "hello", prompt_tokens=0, completion_tokens=0)
    response.usage = None
    client.chat.completions.parse.return_value = response

    result = translation.translate_query(client, "hello")

    assert result.cost_usd == 0.0


def test_translate_query_falls_back_to_original_query_when_empty():
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(
        "", "", prompt_tokens=100, completion_tokens=10,
    )

    result = translation.translate_query(client, "原始查詢")

    assert result.chinese == "原始查詢"
    assert result.english == "原始查詢"
