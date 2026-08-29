"""對話式搜尋的 Conversation Orchestrator：串起 intent.py（意圖判斷／改寫）
與既有 search.py（Hybrid Search，原封不動、不修改排序邏輯），組出這一輪要
顯示給使用者的回覆與結果。見 docs/Claude_Code_Conversational_Video_Search_Prompt.md
的責任區分——LLM 只負責判斷意圖與改寫查詢，實際搜尋一律經過 search.search()，
不允許 LLM 直接產生影片 ID、時間點或搜尋分數。

這個模組本身不碰資料庫：`handle_turn()` 是純函式，永遠回傳全新的
ConversationState，由呼叫端決定要存到哪裡。實際的持久化在
services/conversation_service.py——序列化成 JSON 存進 conversations 表，
讓多輪對話能跨 HTTP request 延續。

Phase 1 只支援 intent.ACTIONS 四種意圖；expand_time_range／
summarize_results（doc 的 Phase 2 範圍）與依 modalities 動態選擇搜尋方式
（doc 的 Phase 3 範圍）都還沒做，見 plan 的分階段實作順序。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import intent as intent_module
from . import search as search_module
from .openai_client import get_client
from .search import SearchResult

logger = logging.getLogger(__name__)

# 對話歷史摘要用純規則累積（不額外呼叫 LLM 摘要，避免每輪多一次 API 成本），
# 超過這個字元數就從最舊的一行開始丟棄，控制傳給 intent.classify_intent()
# 的 prompt 長度不會隨對話輪數無限增長。
_HISTORY_MAX_CHARS = 800


@dataclass
class ConversationState:
    active_query: str | None = None
    active_filters: dict = field(default_factory=dict)  # 目前只用 {"video_ids": list[int]}
    last_results: list[SearchResult] = field(default_factory=list)
    selected_result: SearchResult | None = None
    history_summary: str = ""


@dataclass
class ConversationTurnResult:
    reply_text: str
    results: list[SearchResult]
    cost_usd: float
    new_state: ConversationState
    # 這一輪實際生效的搜尋範圍（空 list＝全部影片）。要回傳出去是因為 LLM 可能
    # 在使用者勾選的範圍內再收窄（見 _resolve_video_ids()），不告訴前端的話，
    # 畫面上勾著 3 支、實際只搜了 1 支，使用者完全無從察覺。
    video_ids: list[int] = field(default_factory=list)


def handle_turn(
    state: ConversationState, user_message: str, ui_video_ids: list[int] | None = None
) -> ConversationTurnResult:
    """處理一輪對話輸入，回傳這輪的回覆文字、要顯示的結果，以及更新後的狀態。
    呼叫端（UI）負責把 new_state 存回去給下一輪使用；這個函式本身不保留任何
    跨呼叫的狀態，方便測試與（理論上）未來要支援多個對話並存時直接沿用。

    ui_video_ids 是使用者在畫面上勾選的搜尋範圍（None／空 list 代表沒有限定）。
    它是**硬邊界**，LLM 從自然語言解析出的範圍只能在其中再收窄，見
    _resolve_video_ids()。
    """
    client = get_client()
    try:
        classification = intent_module.classify_intent(
            client, user_message, state.history_summary, state.last_results
        )
    except Exception as exc:  # API 失敗不讓整輪對話崩潰，退回當作新搜尋處理
        logger.warning("意圖判斷失敗，退回當作新搜尋處理", exc_info=True)
        classification = intent_module.IntentClassification(
            action="new_search",
            standalone_query=user_message,
            filters_video_ids=[],
            selected_result_index=None,
            requires_clarification=False,
            clarification_question=None,
            cost_usd=0.0,
        )

    if classification.requires_clarification or classification.action == "clarify":
        return _handle_clarify(state, user_message, classification)
    if classification.action == "select_result":
        return _handle_select_result(state, user_message, classification)
    return _handle_search(state, user_message, classification, ui_video_ids or [])


def _handle_clarify(
    state: ConversationState, user_message: str, classification: intent_module.IntentClassification
) -> ConversationTurnResult:
    reply_text = classification.clarification_question or "可以再多說明一下想找的內容嗎？"
    new_state = ConversationState(
        active_query=state.active_query,
        active_filters=state.active_filters,
        last_results=state.last_results,
        selected_result=state.selected_result,
        history_summary=_append_history(state.history_summary, user_message, "clarify", reply_text),
    )
    return ConversationTurnResult(
        reply_text=reply_text,
        results=state.last_results,
        cost_usd=classification.cost_usd,
        new_state=new_state,
        video_ids=list(state.active_filters.get("video_ids", [])),
    )


def _handle_select_result(
    state: ConversationState, user_message: str, classification: intent_module.IntentClassification
) -> ConversationTurnResult:
    index = classification.selected_result_index
    valid = index is not None and 1 <= index <= len(state.last_results)
    if not valid:
        reply_text = (
            "不確定指的是上一輪的哪一個結果，可以說明是第幾個，或重新描述想找的內容嗎？"
        )
        new_state = ConversationState(
            active_query=state.active_query,
            active_filters=state.active_filters,
            last_results=state.last_results,
            selected_result=state.selected_result,
            history_summary=_append_history(state.history_summary, user_message, "select_result", reply_text),
        )
        return ConversationTurnResult(
            reply_text=reply_text,
            results=state.last_results,
            cost_usd=classification.cost_usd,
            new_state=new_state,
        )

    selected = state.last_results[index - 1]
    reply_text = (
        f"已選取第 {index} 段：《{selected.video_title}》"
        f"{selected.start_sec:.1f}s–{selected.end_sec:.1f}s"
    )
    new_state = ConversationState(
        active_query=state.active_query,
        active_filters=state.active_filters,
        last_results=state.last_results,
        selected_result=selected,
        history_summary=_append_history(state.history_summary, user_message, "select_result", reply_text),
    )
    return ConversationTurnResult(
        reply_text=reply_text,
        results=[selected],
        cost_usd=classification.cost_usd,
        new_state=new_state,
        video_ids=list(state.active_filters.get("video_ids", [])),
    )


def _handle_search(
    state: ConversationState,
    user_message: str,
    classification: intent_module.IntentClassification,
    ui_video_ids: list[int],
) -> ConversationTurnResult:
    video_ids = _resolve_video_ids(state, classification, ui_video_ids)

    response = search_module.search(
        classification.standalone_query, video_ids=video_ids or None
    )
    reply_text = _build_reply_text(response)

    new_state = ConversationState(
        active_query=classification.standalone_query,
        active_filters={"video_ids": video_ids},
        last_results=response.results,
        selected_result=None,
        history_summary=_append_history(
            state.history_summary, user_message, classification.action, classification.standalone_query
        ),
    )
    return ConversationTurnResult(
        reply_text=reply_text,
        results=response.results,
        cost_usd=classification.cost_usd + response.cost_usd,
        new_state=new_state,
        video_ids=list(video_ids),
    )


def _resolve_video_ids(
    state: ConversationState,
    classification: intent_module.IntentClassification,
    ui_video_ids: list[int],
) -> list[int]:
    """決定這一輪實際要搜的影片範圍（空 list＝全部）。

    使用者在畫面上勾選的 ui_video_ids 是**硬邊界**：LLM 從自然語言解析出的
    範圍（或 refine_search 繼承上一輪的範圍）只能在其中再收窄，不能擴張出去。
    理由是勾選是明確的使用者操作，模型不該默默推翻它——畫面上勾著 3 支、實際
    卻搜了第 4 支，使用者沒有任何線索可以除錯。

    收窄之後變成空集合（LLM 指的影片一支都不在勾選範圍內，通常是它認錯了）
    就整個忽略這次收窄、退回使用者勾選的範圍：這比回傳「零結果」更接近使用者
    的意圖，也不會讓畫面上的範圍跟實際搜尋範圍不一致。
    """
    if classification.filters_video_ids:
        llm_ids = list(classification.filters_video_ids)
    elif classification.action == "refine_search":
        llm_ids = list(state.active_filters.get("video_ids", []))
    else:
        llm_ids = []

    if not ui_video_ids:
        return llm_ids  # 沒有勾選範圍：行為跟加這層之前完全相同

    narrowed = [vid for vid in llm_ids if vid in set(ui_video_ids)]
    return narrowed or list(ui_video_ids)


def _build_reply_text(response: search_module.SearchResponse) -> str:
    if not response.results:
        return "沒有找到足夠相關的片段，可以換個描述方式，或改用人物、動作、物件名稱再試一次。"
    prefix = "" if response.is_confident else "目前搜尋結果的把握度較低，"
    return f"{prefix}找到 {len(response.results)} 個相關片段。"


def _append_history(history_summary: str, user_message: str, action: str, outcome: str) -> str:
    line = f"- 使用者：「{user_message}」→ {action}：{outcome}"
    combined = f"{history_summary}\n{line}" if history_summary else line
    if len(combined) <= _HISTORY_MAX_CHARS:
        return combined
    return combined[-_HISTORY_MAX_CHARS:]
