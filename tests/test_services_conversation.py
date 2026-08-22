"""conversation_service 是薄包裝層，測試重點是正確委派給
pipeline.conversation.handle_turn()。
"""
from __future__ import annotations

from ai_video_search_web.services import conversation_service


def test_send_message_delegates_to_pipeline(monkeypatch):
    captured = {}
    sentinel_state = conversation_service.ConversationState()

    def fake_handle_turn(state, message):
        captured.update(state=state, message=message)
        return "sentinel-turn-result"

    monkeypatch.setattr(conversation_service.conversation_pipeline, "handle_turn", fake_handle_turn)

    result = conversation_service.send_message(sentinel_state, "找出機器人畫面")

    assert result == "sentinel-turn-result"
    assert captured == {"state": sentinel_state, "message": "找出機器人畫面"}
