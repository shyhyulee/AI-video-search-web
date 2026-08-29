"""對話搜尋 API：以 conversations 表持久化 ConversationState，見
docs/09-web-ui-migration-plan.md 3.2 節。"""
from __future__ import annotations

from fastapi import APIRouter

from ..schemas.conversations import ConversationMessageRequest, ConversationOut, ConversationTurnOut
from ..schemas.search import SearchResultOut
from ..services import conversation_service

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationOut, status_code=201)
def start_conversation() -> ConversationOut:
    return ConversationOut(id=conversation_service.start_conversation())


@router.get("/{conversation_id}", response_model=ConversationTurnOut)
def get_conversation(conversation_id: int) -> ConversationTurnOut:
    state = conversation_service.get_conversation_state(conversation_id)
    if state is None:
        raise conversation_service.ConversationNotFoundError(f"找不到對話 {conversation_id}")
    return ConversationTurnOut(
        reply_text="",
        results=[SearchResultOut.from_result(r) for r in state.last_results],
        cost_usd=0.0,
        video_ids=list(state.active_filters.get("video_ids", [])),
    )


@router.post("/{conversation_id}/messages", response_model=ConversationTurnOut)
def send_message(conversation_id: int, payload: ConversationMessageRequest) -> ConversationTurnOut:
    turn_result = conversation_service.send_message_by_id(
        conversation_id, payload.message, payload.video_ids
    )
    return ConversationTurnOut(
        reply_text=turn_result.reply_text,
        results=[SearchResultOut.from_result(r) for r in turn_result.results],
        cost_usd=turn_result.cost_usd,
        video_ids=turn_result.video_ids,
    )
