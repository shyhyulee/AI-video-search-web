"""conversations API：monkeypatch conversation_pipeline.handle_turn 避免真的
呼叫 OpenAI（intent 判斷＋search），重點測 conversation_id 的持久化與狀態
往返。
"""
from __future__ import annotations

from ai_video_search_web.pipeline import conversation as conversation_pipeline
from ai_video_search_web.pipeline.conversation import ConversationState, ConversationTurnResult


def test_start_conversation_returns_id(client):
    resp = client.post("/api/v1/conversations")
    assert resp.status_code == 201
    assert isinstance(resp.json()["id"], int)


def test_get_conversation_not_found_returns_404(client):
    resp = client.get("/api/v1/conversations/999")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


def test_get_conversation_returns_empty_state_for_new_conversation(client):
    conversation_id = client.post("/api/v1/conversations").json()["id"]
    resp = client.get(f"/api/v1/conversations/{conversation_id}")
    assert resp.status_code == 200
    assert resp.json() == {"reply_text": "", "results": [], "cost_usd": 0.0, "video_ids": []}


def test_send_message_persists_new_state(client, monkeypatch):
    def fake_handle_turn(
        state: ConversationState, message: str, ui_video_ids=None
    ) -> ConversationTurnResult:
        new_state = ConversationState(active_query=message, history_summary=f"問過：{message}")
        return ConversationTurnResult(
            reply_text=f"收到：{message}", results=[], cost_usd=0.002, new_state=new_state,
        )

    monkeypatch.setattr(conversation_pipeline, "handle_turn", fake_handle_turn)

    conversation_id = client.post("/api/v1/conversations").json()["id"]
    resp = client.post(f"/api/v1/conversations/{conversation_id}/messages", json={"message": "找機器人"})

    assert resp.status_code == 200
    assert resp.json()["reply_text"] == "收到：找機器人"
    assert resp.json()["cost_usd"] == 0.002

    # 第二輪應該讀到第一輪寫回去的新狀態，而不是空白初始狀態。
    captured_states = []

    def capture_state(
        state: ConversationState, message: str, ui_video_ids=None
    ) -> ConversationTurnResult:
        captured_states.append(state)
        return ConversationTurnResult(reply_text="ok", results=[], cost_usd=0.0, new_state=state)

    monkeypatch.setattr(conversation_pipeline, "handle_turn", capture_state)
    client.post(f"/api/v1/conversations/{conversation_id}/messages", json={"message": "第二句"})

    assert captured_states[0].active_query == "找機器人"
    assert captured_states[0].history_summary == "問過：找機器人"


def test_send_message_passes_ui_scope_and_returns_effective_scope(client, monkeypatch):
    """畫面上勾選的範圍要送到 handle_turn()，實際生效的範圍要回傳給前端。"""
    captured = {}

    def fake_handle_turn(
        state: ConversationState, message: str, ui_video_ids=None
    ) -> ConversationTurnResult:
        captured["ui_video_ids"] = ui_video_ids
        # 模擬 LLM 在勾選範圍內再收窄成一支
        return ConversationTurnResult(
            reply_text="ok", results=[], cost_usd=0.0, new_state=state, video_ids=[8],
        )

    monkeypatch.setattr(conversation_pipeline, "handle_turn", fake_handle_turn)

    conversation_id = client.post("/api/v1/conversations").json()["id"]
    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message": "找生產線", "video_ids": [4, 8, 15]},
    )

    assert resp.status_code == 200
    assert captured["ui_video_ids"] == [4, 8, 15]
    assert resp.json()["video_ids"] == [8]


def test_send_message_to_missing_conversation_returns_404(client):
    resp = client.post("/api/v1/conversations/999/messages", json={"message": "hi"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
