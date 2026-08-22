"""summary.py 的摘要產生與成本計算測試：mock OpenAI client，不呼叫真實 API。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ai_video_search_web.pipeline import summary


def _segment(start_sec: float = 0.0, transcript: str | None = None, visual_description: str | None = None):
    return SimpleNamespace(start_sec=start_sec, transcript=transcript, visual_description=visual_description)


def _fake_response(content: str, prompt_tokens: int, completion_tokens: int):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def test_generate_summary_computes_cost_from_usage():
    client = MagicMock()
    client.chat.completions.create.return_value = _fake_response(
        "這是一段摘要。", prompt_tokens=2000, completion_tokens=150,
    )

    result = summary.generate_summary(client, [_segment(transcript="哈囉")])

    assert result.summary == "這是一段摘要。"
    expected_cost = 2000 * summary.PRICE_INPUT_PER_TOKEN_USD + 150 * summary.PRICE_OUTPUT_PER_TOKEN_USD
    assert result.cost_usd == pytest.approx(expected_cost)


def test_generate_summary_missing_usage_returns_zero_cost():
    client = MagicMock()
    response = _fake_response("摘要", prompt_tokens=0, completion_tokens=0)
    response.usage = None
    client.chat.completions.create.return_value = response

    result = summary.generate_summary(client, [_segment(transcript="哈囉")])

    assert result.cost_usd == 0.0


def test_generate_summary_raises_without_segments():
    with pytest.raises(ValueError):
        summary.generate_summary(MagicMock(), [])
