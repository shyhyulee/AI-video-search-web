from __future__ import annotations

from pydantic import BaseModel

from .search import SearchResultOut


class ConversationOut(BaseModel):
    id: int


class ConversationMessageRequest(BaseModel):
    message: str


class ConversationTurnOut(BaseModel):
    reply_text: str
    results: list[SearchResultOut]
    cost_usd: float
