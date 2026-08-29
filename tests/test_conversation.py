"""conversation.py 的 Conversation Orchestrator 測試：monkeypatch
intent.classify_intent／search.search／get_client，不呼叫真實 API，只驗證
狀態機邏輯（action 分派、filters 沿用、history 截斷）。"""
from __future__ import annotations

from unittest.mock import MagicMock

from ai_video_search_web.pipeline import conversation
from ai_video_search_web.pipeline.intent import IntentClassification
from ai_video_search_web.pipeline.search import SearchResponse, SearchResult


def _result(video_id: int = 1, video_title: str = "測試影片", start: float = 1.0, end: float = 5.0) -> SearchResult:
    return SearchResult(
        segment_id=1, video_id=video_id, video_title=video_title, start_sec=start, end_sec=end,
        similarity=0.8, hit_source="畫面", description="描述",
        transcript=None, transcript_score=None, visual_score=0.8, ocr_score=None,
        fusion_strategy="",
    )


def _classification(**overrides) -> IntentClassification:
    defaults = dict(
        action="new_search",
        standalone_query="找出工廠中有人出現的片段",
        filters_video_ids=[],
        selected_result_index=None,
        requires_clarification=False,
        clarification_question=None,
        cost_usd=0.001,
    )
    defaults.update(overrides)
    return IntentClassification(**defaults)


def _patch_client(monkeypatch) -> None:
    monkeypatch.setattr(conversation, "get_client", lambda: MagicMock())


# ----------------------------------------------------------------------
# handle_turn()：new_search／refine_search 走搜尋分支
# ----------------------------------------------------------------------


def test_handle_turn_new_search_calls_search_and_builds_reply(monkeypatch):
    _patch_client(monkeypatch)
    monkeypatch.setattr(conversation.intent_module, "classify_intent", lambda *a, **k: _classification())
    results = [_result()]
    monkeypatch.setattr(
        conversation.search_module, "search",
        lambda query, video_ids=None: SearchResponse(results=results, cost_usd=0.01, is_confident=True),
    )

    state = conversation.ConversationState()
    turn = conversation.handle_turn(state, "找出有人進入生產線的畫面")

    assert turn.results == results
    assert turn.reply_text == "找到 1 個相關片段。"
    assert turn.cost_usd == 0.001 + 0.01
    assert turn.new_state.last_results == results
    assert turn.new_state.active_query == "找出工廠中有人出現的片段"


def test_handle_turn_no_results_reply_says_not_found(monkeypatch):
    _patch_client(monkeypatch)
    monkeypatch.setattr(conversation.intent_module, "classify_intent", lambda *a, **k: _classification())
    monkeypatch.setattr(
        conversation.search_module, "search",
        lambda query, video_ids=None: SearchResponse(results=[], cost_usd=0.0, is_confident=False),
    )

    turn = conversation.handle_turn(conversation.ConversationState(), "找出不存在的東西")

    assert "沒有找到" in turn.reply_text
    assert turn.results == []


def test_handle_turn_low_confidence_reply_has_prefix(monkeypatch):
    _patch_client(monkeypatch)
    monkeypatch.setattr(conversation.intent_module, "classify_intent", lambda *a, **k: _classification())
    monkeypatch.setattr(
        conversation.search_module, "search",
        lambda query, video_ids=None: SearchResponse(results=[_result()], cost_usd=0.0, is_confident=False),
    )

    turn = conversation.handle_turn(conversation.ConversationState(), "模糊的查詢")

    assert turn.reply_text.startswith("目前搜尋結果的把握度較低，")


def test_handle_turn_refine_search_carries_over_previous_video_filter(monkeypatch):
    _patch_client(monkeypatch)
    monkeypatch.setattr(
        conversation.intent_module, "classify_intent",
        lambda *a, **k: _classification(action="refine_search", filters_video_ids=[]),
    )
    captured = {}

    def _fake_search(query, video_ids=None):
        captured["video_ids"] = video_ids
        return SearchResponse(results=[_result()], cost_usd=0.0, is_confident=True)

    monkeypatch.setattr(conversation.search_module, "search", _fake_search)

    state = conversation.ConversationState(active_filters={"video_ids": [7]})
    conversation.handle_turn(state, "只看穿紅色衣服的人")

    assert captured["video_ids"] == [7]


def test_handle_turn_new_search_ignores_previous_filters(monkeypatch):
    _patch_client(monkeypatch)
    monkeypatch.setattr(
        conversation.intent_module, "classify_intent",
        lambda *a, **k: _classification(action="new_search", filters_video_ids=[]),
    )
    captured = {}

    def _fake_search(query, video_ids=None):
        captured["video_ids"] = video_ids
        return SearchResponse(results=[], cost_usd=0.0, is_confident=False)

    monkeypatch.setattr(conversation.search_module, "search", _fake_search)

    state = conversation.ConversationState(active_filters={"video_ids": [7]})
    conversation.handle_turn(state, "找別的東西")

    assert captured["video_ids"] is None


# ----------------------------------------------------------------------
# handle_turn()：select_result 走選取分支，不呼叫 search()
# ----------------------------------------------------------------------


def test_handle_turn_select_result_valid_index_returns_selected_only(monkeypatch):
    _patch_client(monkeypatch)
    monkeypatch.setattr(
        conversation.intent_module, "classify_intent",
        lambda *a, **k: _classification(action="select_result", selected_result_index=2),
    )
    monkeypatch.setattr(
        conversation.search_module, "search",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("select_result 不應該呼叫 search()")),
    )

    first, second = _result(video_title="第一段"), _result(video_title="第二段")
    state = conversation.ConversationState(last_results=[first, second])
    turn = conversation.handle_turn(state, "播放第二段")

    assert turn.results == [second]
    assert turn.new_state.selected_result == second
    assert turn.new_state.last_results == [first, second]  # 清單本身不變，供之後再選別的項目
    assert "第 2 段" in turn.reply_text


def test_handle_turn_select_result_invalid_index_asks_for_clarification(monkeypatch):
    _patch_client(monkeypatch)
    monkeypatch.setattr(
        conversation.intent_module, "classify_intent",
        lambda *a, **k: _classification(action="select_result", selected_result_index=99),
    )

    state = conversation.ConversationState(last_results=[_result()])
    turn = conversation.handle_turn(state, "播放第九十九段")

    assert "不確定" in turn.reply_text
    assert turn.new_state.selected_result is None


def test_handle_turn_select_result_no_previous_results_asks_for_clarification(monkeypatch):
    _patch_client(monkeypatch)
    monkeypatch.setattr(
        conversation.intent_module, "classify_intent",
        lambda *a, **k: _classification(action="select_result", selected_result_index=1),
    )

    turn = conversation.handle_turn(conversation.ConversationState(), "播放第一段")

    assert "不確定" in turn.reply_text


# ----------------------------------------------------------------------
# handle_turn()：clarify／requires_clarification
# ----------------------------------------------------------------------


def test_handle_turn_clarify_action_returns_question(monkeypatch):
    _patch_client(monkeypatch)
    monkeypatch.setattr(
        conversation.intent_module, "classify_intent",
        lambda *a, **k: _classification(action="clarify", clarification_question="想找哪一種畫面？"),
    )

    turn = conversation.handle_turn(conversation.ConversationState(), "幫我找")

    assert turn.reply_text == "想找哪一種畫面？"


def test_handle_turn_requires_clarification_flag_overrides_action(monkeypatch):
    _patch_client(monkeypatch)
    monkeypatch.setattr(
        conversation.intent_module, "classify_intent",
        lambda *a, **k: _classification(
            action="new_search", requires_clarification=True, clarification_question="可以再說明嗎？"
        ),
    )
    monkeypatch.setattr(
        conversation.search_module, "search",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("requires_clarification 時不應該呼叫 search()")),
    )

    turn = conversation.handle_turn(conversation.ConversationState(), "隨便")

    assert turn.reply_text == "可以再說明嗎？"


# ----------------------------------------------------------------------
# _append_history()：純字串截斷邏輯，不呼叫 API
# ----------------------------------------------------------------------


def test_append_history_truncates_when_exceeds_max_chars():
    long_summary = "x" * (conversation._HISTORY_MAX_CHARS - 5)
    result = conversation._append_history(long_summary, "使用者輸入", "new_search", "outcome")
    assert len(result) <= conversation._HISTORY_MAX_CHARS


def test_append_history_appends_new_line_when_under_limit():
    result = conversation._append_history("- 第一輪", "第二句話", "refine_search", "改寫後查詢")
    assert result.startswith("- 第一輪\n")
    assert "第二句話" in result


# ----------------------------------------------------------------------
# _resolve_video_ids()：純邏輯，不呼叫 API
# ----------------------------------------------------------------------


def test_resolve_video_ids_explicit_filters_override_previous():
    state = conversation.ConversationState(active_filters={"video_ids": [1]})
    classification = _classification(action="refine_search", filters_video_ids=[9])
    assert conversation._resolve_video_ids(state, classification, []) == [9]


def test_resolve_video_ids_refine_search_falls_back_to_previous_when_none_given():
    state = conversation.ConversationState(active_filters={"video_ids": [3]})
    classification = _classification(action="refine_search", filters_video_ids=[])
    assert conversation._resolve_video_ids(state, classification, []) == [3]


def test_resolve_video_ids_new_search_ignores_previous_filters():
    state = conversation.ConversationState(active_filters={"video_ids": [3]})
    classification = _classification(action="new_search", filters_video_ids=[])
    assert conversation._resolve_video_ids(state, classification, []) == []


# ----------------------------------------------------------------------
# _resolve_video_ids()：使用者勾選的範圍是硬邊界，LLM 只能在其中收窄
# ----------------------------------------------------------------------


def test_resolve_video_ids_ui_scope_used_when_llm_gives_none():
    """LLM 沒指定範圍時，直接用使用者勾選的那批。"""
    state = conversation.ConversationState()
    classification = _classification(action="new_search", filters_video_ids=[])
    assert conversation._resolve_video_ids(state, classification, [4, 8, 15]) == [4, 8, 15]


def test_resolve_video_ids_llm_narrows_within_ui_scope():
    """LLM 指到勾選範圍內的子集：收窄成立。"""
    state = conversation.ConversationState()
    classification = _classification(action="new_search", filters_video_ids=[8])
    assert conversation._resolve_video_ids(state, classification, [4, 8, 15]) == [8]


def test_resolve_video_ids_llm_cannot_escape_ui_scope():
    """LLM 指到勾選範圍外的影片：不能擴張出去，那幾個 id 直接被丟掉。"""
    state = conversation.ConversationState()
    classification = _classification(action="new_search", filters_video_ids=[8, 99])
    assert conversation._resolve_video_ids(state, classification, [4, 8, 15]) == [8]


def test_resolve_video_ids_empty_intersection_falls_back_to_ui_scope():
    """LLM 指的影片一支都不在勾選範圍內（通常是它認錯了）：整個忽略這次收窄，
    退回使用者勾選的範圍，而不是搜出零筆。"""
    state = conversation.ConversationState()
    classification = _classification(action="new_search", filters_video_ids=[99])
    assert conversation._resolve_video_ids(state, classification, [4, 8]) == [4, 8]


def test_resolve_video_ids_ui_scope_also_bounds_carried_over_filters():
    """refine_search 繼承上一輪的範圍時，一樣受勾選範圍限制。"""
    state = conversation.ConversationState(active_filters={"video_ids": [3, 8]})
    classification = _classification(action="refine_search", filters_video_ids=[])
    assert conversation._resolve_video_ids(state, classification, [8, 15]) == [8]


def test_handle_turn_ui_scope_reaches_search_and_is_reported_back(monkeypatch):
    """端到端：勾選範圍要真的傳進 search()，也要回報在 turn.video_ids 上。"""
    _patch_client(monkeypatch)
    monkeypatch.setattr(
        conversation.intent_module, "classify_intent",
        lambda *a, **k: _classification(action="new_search", filters_video_ids=[]),
    )
    captured = {}

    def _fake_search(query, video_ids=None):
        captured["video_ids"] = video_ids
        return SearchResponse(results=[_result()], cost_usd=0.0, is_confident=True)

    monkeypatch.setattr(conversation.search_module, "search", _fake_search)

    turn = conversation.handle_turn(conversation.ConversationState(), "找生產線", [4, 8])

    assert captured["video_ids"] == [4, 8]
    assert turn.video_ids == [4, 8]
    assert turn.new_state.active_filters == {"video_ids": [4, 8]}
