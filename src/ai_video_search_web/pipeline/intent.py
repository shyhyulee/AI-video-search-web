"""對話式搜尋的意圖判斷與 Query Rewriter：把使用者這一輪的自然語言輸入，
結合對話歷史摘要與上一輪結果，轉成 pipeline/conversation.py 可以直接
執行的結構化意圖。LLM 只負責「判斷意圖、改寫成獨立查詢字串」，不直接
呼叫搜尋、不接觸資料庫，符合 docs/Claude_Code_Conversational_Video_Search_Prompt.md
「LLM：判斷意圖、改寫 Query...；Search Service：執行搜尋」的責任區分。

Phase 1 只支援四種 action（new_search／refine_search／select_result／
clarify）；expand_time_range／summarize_results 留到 Phase 2 再加，見
plan 的分階段實作順序。刻意不輸出 doc 原始 schema 裡的 query_type／
modalities 欄位——現有 search.py 沒有依這兩者改變行為的能力，留著只是
LLM 產生了也沒人用的欄位，容易誤導之後的維護者以為已經生效。

跟 translation.py 一樣：V0 只接 OpenAI，用 chat.completions.parse +
Pydantic model 拿結構化輸出，對外只暴露 provider 無關的介面。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel

from .openai_client import chat_completion_cost, chat_prices
from .search import SearchResult

MODEL_NAME = "gpt-4o-mini"
# 單價跟著 MODEL_NAME 走，不再各自寫死一份，見 openai_client._CHAT_PRICES_USD_PER_TOKEN。
PRICE_INPUT_PER_TOKEN_USD, PRICE_OUTPUT_PER_TOKEN_USD = chat_prices(MODEL_NAME)

ACTIONS = ("new_search", "refine_search", "select_result", "clarify")

_PROMPT_TEMPLATE = """\
你是一個影片搜尋助理的意圖判斷模組。根據「對話歷史摘要」「上一輪搜尋結果」
與「使用者這一輪輸入」，判斷使用者的意圖，並輸出結構化結果。

action 只能是以下四種之一：
- new_search：全新搜尋，跟先前的搜尋主題無關，或使用者明確要換題目。
- refine_search：在既有搜尋基礎上增加、修改或縮小條件（例如「只看穿紅色衣服的人」），
  需要重新搜尋。
- select_result：使用者指的是「上一輪搜尋結果」裡的某一個項目（例如「第二段」
  「剛才那個」「播放第一個」），不需要重新搜尋。
- clarify：使用者輸入資訊不足以判斷要搜尋或選取什麼，需要反問澄清。

standalone_query：把使用者這句話結合對話歷史，改寫成一句「不需要對話上下文也
看得懂」的完整獨立查詢字串（給後續的搜尋引擎用）。action 是 select_result 或
clarify 時，這個查詢不會真的被拿去搜尋，直接照抄使用者原句即可。

filters_video_ids：只有使用者明確要求限定在特定影片時才填入對應的 video_id；
不確定或沒有特別要求，回傳空陣列，不要自己猜測或沿用之前的範圍（沿用邏輯由
呼叫端負責，不是你的工作）。

selected_result_index：只有 action 是 select_result 時才需要填，代表使用者指的
是「上一輪搜尋結果」清單中第幾項（清單前面標的數字，1-based）；其他 action
一律填 null。如果使用者的指代看不出對應清單中的哪一項，改用 clarify。

requires_clarification／clarification_question：資訊不足以繼續（例如沒有上一輪
結果卻要「播放第二段」、或完全看不懂使用者要找什麼）時，requires_clarification
填 true 並給出一句繁體中文的反問句；否則 requires_clarification 填 false、
clarification_question 填 null。

對話歷史摘要：
{history_summary}

上一輪搜尋結果：
{results_context}

使用者這一輪輸入：
{user_message}
"""

_NO_HISTORY = "（無，這是對話的第一輪）"
_NO_RESULTS = "（無，上一輪沒有搜尋結果可供選取）"


class _IntentSchema(BaseModel):
    action: Literal["new_search", "refine_search", "select_result", "clarify"]
    standalone_query: str
    filters_video_ids: list[int]
    selected_result_index: int | None
    requires_clarification: bool
    clarification_question: str | None


@dataclass
class IntentClassification:
    action: Literal["new_search", "refine_search", "select_result", "clarify"]
    standalone_query: str
    filters_video_ids: list[int]
    selected_result_index: int | None
    requires_clarification: bool
    clarification_question: str | None
    cost_usd: float


def _format_results_context(results: list[SearchResult]) -> str:
    if not results:
        return _NO_RESULTS
    lines = []
    for index, result in enumerate(results, start=1):
        time_range = f"{result.start_sec:.1f}s–{result.end_sec:.1f}s"
        lines.append(f"{index}.《{result.video_title}》{time_range}：{result.description}")
    return "\n".join(lines)


def classify_intent(
    client: OpenAI,
    user_message: str,
    history_summary: str,
    last_results: list[SearchResult],
) -> IntentClassification:
    """判斷這一輪的對話意圖並改寫查詢。呼叫端要自行處理例外（例如 API 失敗
    時退回 new_search、直接拿使用者原句當查詢），這個函式不吞例外——跟
    translation.translate_query() 的分工方式一致。
    """
    prompt = _PROMPT_TEMPLATE.format(
        history_summary=history_summary.strip() or _NO_HISTORY,
        results_context=_format_results_context(last_results),
        user_message=user_message,
    )
    response = client.chat.completions.parse(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        response_format=_IntentSchema,
        max_completion_tokens=400,
    )
    parsed = response.choices[0].message.parsed
    cost_usd = chat_completion_cost(response.usage, PRICE_INPUT_PER_TOKEN_USD, PRICE_OUTPUT_PER_TOKEN_USD)

    if parsed is None:
        # structured output 解析失敗（理論上罕見）：退回 new_search、直接用
        # 使用者原句查詢，不讓意圖判斷失敗擋住整個對話。
        return IntentClassification(
            action="new_search",
            standalone_query=user_message,
            filters_video_ids=[],
            selected_result_index=None,
            requires_clarification=False,
            clarification_question=None,
            cost_usd=cost_usd,
        )

    return IntentClassification(
        action=parsed.action,
        standalone_query=parsed.standalone_query.strip() or user_message,
        filters_video_ids=list(parsed.filters_video_ids),
        selected_result_index=parsed.selected_result_index,
        requires_clarification=parsed.requires_clarification,
        clarification_question=parsed.clarification_question,
        cost_usd=cost_usd,
    )
