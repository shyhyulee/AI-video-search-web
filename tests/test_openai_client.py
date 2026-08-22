"""openai_client.chat_completion_cost()：vlm.py／summary.py／translation.py 共用的
chat completion 成本計算公式，純算術、不呼叫任何 API。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_video_search_web.pipeline.openai_client import chat_completion_cost


def test_chat_completion_cost_computes_from_usage():
    usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=100)
    assert chat_completion_cost(usage, price_input_per_token=0.15 / 1_000_000, price_output_per_token=0.60 / 1_000_000) == pytest.approx(
        1000 * 0.15 / 1_000_000 + 100 * 0.60 / 1_000_000
    )


def test_chat_completion_cost_none_usage_returns_zero():
    assert chat_completion_cost(None, price_input_per_token=0.15 / 1_000_000, price_output_per_token=0.60 / 1_000_000) == 0.0
