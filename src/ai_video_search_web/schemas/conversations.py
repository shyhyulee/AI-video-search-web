from __future__ import annotations

from pydantic import BaseModel

from .search import SearchResultOut


class ConversationOut(BaseModel):
    id: int


class ConversationMessageRequest(BaseModel):
    message: str
    # 使用者在畫面上勾選的搜尋範圍（省略／null＝不限定）。每輪都重送，不存進
    # conversations 表，理由見 services/conversation_service.send_message_by_id()。
    video_ids: list[int] | None = None


class ConversationTurnOut(BaseModel):
    reply_text: str
    results: list[SearchResultOut]
    cost_usd: float
    # 這一輪實際生效的範圍（空 list＝全部影片）。LLM 可能在勾選範圍內再收窄，
    # 前端要拿這個跟畫面上勾選的比對，才能告訴使用者實際搜了哪幾支。
    video_ids: list[int] = []
