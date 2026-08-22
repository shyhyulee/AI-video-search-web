"""intent.py 的意圖判斷與 Query Rewriter 測試：mock OpenAI client，不呼叫
真實 API，比照 tests/test_translation.py 的模式。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ai_video_search_web.pipeline import intent
from ai_video_search_web.pipeline.search import SearchResult


def _result(video_title: str = "測試影片", start: float = 1.0, end: float = 5.0, description: str = "描述") -> SearchResult:
    return SearchResult(
        segment_id=1, video_id=1, video_title=video_title, start_sec=start, end_sec=end,
        similarity=0.8, hit_source="畫面", description=description,
        transcript=None, transcript_score=None, visual_score=0.8, ocr_score=None,
        fusion_strategy="",
    )


def _fake_response(parsed: SimpleNamespace | None, prompt_tokens: int = 100, completion_tokens: int = 20):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def _fake_parsed(**overrides) -> SimpleNamespace:
    defaults = dict(
        action="new_search",
        standalone_query="找出工廠中有人出現的片段",
        filters_video_ids=[],
        selected_result_index=None,
        requires_clarification=False,
        clarification_question=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ----------------------------------------------------------------------
# _format_results_context()：純字串格式化，不呼叫 API
# ----------------------------------------------------------------------


def test_format_results_context_empty_returns_placeholder():
    assert intent._format_results_context([]) == intent._NO_RESULTS


def test_format_results_context_formats_indexed_list():
    results = [_result(video_title="影片A", start=1.0, end=5.0, description="有人走進工廠")]
    context = intent._format_results_context(results)
    assert context == "1.《影片A》1.0s–5.0s：有人走進工廠"


def test_format_results_context_uses_one_based_index_matching_display_order():
    results = [_result(video_title="A"), _result(video_title="B")]
    context = intent._format_results_context(results)
    assert context.splitlines()[0].startswith("1.")
    assert context.splitlines()[1].startswith("2.")


# ----------------------------------------------------------------------
# classify_intent()：mock client，驗證欄位對應與成本計算
# ----------------------------------------------------------------------


def test_classify_intent_computes_cost_from_usage():
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(
        _fake_parsed(), prompt_tokens=300, completion_tokens=20,
    )

    result = intent.classify_intent(client, "找出有人進入生產線的畫面", "", [])

    assert result.action == "new_search"
    expected_cost = 300 * intent.PRICE_INPUT_PER_TOKEN_USD + 20 * intent.PRICE_OUTPUT_PER_TOKEN_USD
    assert result.cost_usd == pytest.approx(expected_cost)


def test_classify_intent_maps_select_result_fields():
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(
        _fake_parsed(action="select_result", selected_result_index=2, standalone_query="播放第二段"),
    )

    result = intent.classify_intent(client, "播放第二段", "history", [_result(), _result()])

    assert result.action == "select_result"
    assert result.selected_result_index == 2


def test_classify_intent_falls_back_to_new_search_when_parsed_is_none():
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(None)

    result = intent.classify_intent(client, "使用者原句", "", [])

    assert result.action == "new_search"
    assert result.standalone_query == "使用者原句"
    assert result.requires_clarification is False


def test_classify_intent_empty_standalone_query_falls_back_to_user_message():
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(
        _fake_parsed(standalone_query=""),
    )

    result = intent.classify_intent(client, "使用者原句", "", [])

    assert result.standalone_query == "使用者原句"
