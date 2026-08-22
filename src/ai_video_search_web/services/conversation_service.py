"""對話搜尋 Application Service：薄包裝 pipeline.conversation.handle_turn()。

Tkinter（Phase 1）繼續用 send_message(state, message) 純記憶體介面，不受
影響。Phase 2 新增以 conversations 表持久化 ConversationState，讓 Web 版
的多輪對話能跨 HTTP request（甚至跨伺服器重啟）延續——這是刻意補上的，因為
pipeline/conversation.py 的模組說明明講原設計「本機單人 Tkinter 桌面 App，
不需要 conversation_id」，這個假設在 Web 化後不成立，見
docs/09-web-ui-migration-plan.md 2.2／3.2 節。

`handle_turn()` 本身是純函式（永遠回傳全新 state，不原地修改），且
ConversationState／SearchResult 全部欄位是 str/int/float/None/list，可直接
JSON 序列化，這裡不需要改動 pipeline/conversation.py 一行程式碼。
"""
from __future__ import annotations

import dataclasses
import json

from .. import db
from ..pipeline import conversation as conversation_pipeline
from ..pipeline.conversation import ConversationState, ConversationTurnResult
from ..pipeline.search import SearchResult

__all__ = [
    "ConversationState",
    "ConversationTurnResult",
    "SearchResult",
    "ConversationNotFoundError",
    "send_message",
    "start_conversation",
    "get_conversation_state",
    "send_message_by_id",
]


class ConversationNotFoundError(Exception):
    """找不到指定的 conversation_id。"""


def send_message(state: ConversationState, message: str) -> ConversationTurnResult:
    return conversation_pipeline.handle_turn(state, message)


def start_conversation() -> int:
    """建立一個新的空對話，回傳 conversation_id。"""
    state_json = json.dumps(dataclasses.asdict(ConversationState()))
    return db.insert_conversation(state_json)


def get_conversation_state(conversation_id: int) -> ConversationState | None:
    record = db.get_conversation(conversation_id)
    if record is None:
        return None
    return _state_from_json(record.state_json)


def send_message_by_id(conversation_id: int, message: str) -> ConversationTurnResult:
    """讀出目前狀態、呼叫 handle_turn()、把新狀態與這輪花費寫回去，供
    FastAPI 對話 API 使用。"""
    record = db.get_conversation(conversation_id)
    if record is None:
        raise ConversationNotFoundError(f"找不到對話 {conversation_id}")

    state = _state_from_json(record.state_json)
    turn_result = conversation_pipeline.handle_turn(state, message)
    new_state_json = json.dumps(dataclasses.asdict(turn_result.new_state))
    db.update_conversation(conversation_id, new_state_json, turn_result.cost_usd)
    return turn_result


def _state_from_json(state_json: str) -> ConversationState:
    raw = json.loads(state_json)
    last_results = [SearchResult(**r) for r in raw.get("last_results", [])]
    selected_raw = raw.get("selected_result")
    selected_result = SearchResult(**selected_raw) if selected_raw is not None else None
    return ConversationState(
        active_query=raw.get("active_query"),
        active_filters=raw.get("active_filters", {}),
        last_results=last_results,
        selected_result=selected_result,
        history_summary=raw.get("history_summary", ""),
    )
