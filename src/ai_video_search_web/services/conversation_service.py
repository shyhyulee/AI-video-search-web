"""對話搜尋 Application Service：薄包裝 pipeline.conversation.handle_turn()。
Phase 1 維持呼叫端（Tkinter）自行持有 ConversationState 的記憶體模式，還沒接
資料庫（見 docs/09-web-ui-migration-plan.md 的 conversations 表，屬於 Phase 2）。
"""
from __future__ import annotations

from ..pipeline import conversation as conversation_pipeline
from ..pipeline.conversation import ConversationState, ConversationTurnResult
from ..pipeline.search import SearchResult

__all__ = ["ConversationState", "ConversationTurnResult", "SearchResult", "send_message"]


def send_message(state: ConversationState, message: str) -> ConversationTurnResult:
    return conversation_pipeline.handle_turn(state, message)
