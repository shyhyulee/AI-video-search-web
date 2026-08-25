"""統一錯誤處理：把 services 層丟出的例外轉成穩定的 Error Schema，不直接把
Python traceback 回傳給前端，見 docs/09-web-ui-migration-plan.md（沿用
docs/08-web-ui-migration-design.md 第 6 節的 Error Schema 格式）。
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..services import job_manager
from ..services.conversation_service import ConversationNotFoundError
from ..services.youtube_search_service import YoutubeSearchError

_ERROR_MAP: dict[type[Exception], tuple[int, str]] = {
    job_manager.VideoNotFoundError: (404, "VIDEO_NOT_FOUND"),
    job_manager.DuplicateJobError: (409, "DUPLICATE_JOB"),
    job_manager.DurationLimitExceededError: (422, "DURATION_LIMIT_EXCEEDED"),
    job_manager.InvalidUrlError: (400, "INVALID_URL"),
    job_manager.JobNotFoundError: (404, "JOB_NOT_FOUND"),
    job_manager.InvalidJobStateError: (409, "INVALID_JOB_STATE"),
    ConversationNotFoundError: (404, "CONVERSATION_NOT_FOUND"),
    # 502：失敗的是上游的 YouTube／yt-dlp，不是使用者的請求有問題。
    YoutubeSearchError: (502, "YOUTUBE_SEARCH_FAILED"),
}


def install_exception_handlers(app: FastAPI) -> None:
    for exc_type, (status_code, code) in _ERROR_MAP.items():
        app.add_exception_handler(exc_type, _make_handler(status_code, code))


def _make_handler(status_code: int, code: str):
    async def _handler(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={"error": {"code": code, "message": str(exc), "details": None}},
        )

    return _handler
