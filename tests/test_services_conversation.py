"""conversation_service 以 conversations 表持久化 ConversationState；這裡
測 start_conversation／get_conversation_state／send_message_by_id 對 DB 的
讀寫是否正確，pipeline.conversation.handle_turn() 本身的邏輯已經在
test_conversation.py 測過，這裡用 monkeypatch 換掉它，只測狀態持久化這一層。
"""
from __future__ import annotations

import pytest

from ai_video_search_web import db
from ai_video_search_web.pipeline.conversation import ConversationState, ConversationTurnResult
from ai_video_search_web.services import conversation_service


def test_start_conversation_creates_empty_state(temp_db):
    conversation_id = conversation_service.start_conversation()

    state = conversation_service.get_conversation_state(conversation_id)

    assert state == ConversationState()


def test_get_conversation_state_returns_none_when_missing(temp_db):
    assert conversation_service.get_conversation_state(999) is None


def test_send_message_by_id_persists_new_state_and_cost(temp_db, monkeypatch):
    conversation_id = conversation_service.start_conversation()

    new_state = ConversationState(active_query="找機器人", history_summary="問過：找機器人")

    def fake_handle_turn(state, message):
        assert state == ConversationState()
        assert message == "找機器人"
        return ConversationTurnResult(reply_text="找到 3 個相關片段。", results=[], cost_usd=0.002, new_state=new_state)

    monkeypatch.setattr(conversation_service.conversation_pipeline, "handle_turn", fake_handle_turn)

    turn_result = conversation_service.send_message_by_id(conversation_id, "找機器人")

    assert turn_result.reply_text == "找到 3 個相關片段。"
    assert conversation_service.get_conversation_state(conversation_id) == new_state

    record = db.get_conversation(conversation_id)
    assert record.total_cost_usd == pytest.approx(0.002)


def test_send_message_by_id_raises_when_conversation_missing(temp_db):
    with pytest.raises(conversation_service.ConversationNotFoundError):
        conversation_service.send_message_by_id(999, "hi")
