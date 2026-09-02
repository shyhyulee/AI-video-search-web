"""統一錯誤處理：把 services 層丟出的例外轉成穩定的 Error Schema，不直接把
Python traceback 回傳給前端，見 docs/archive/09-web-ui-migration-plan.md（沿用
docs/prompts/08-web-ui-migration-design.md 第 6 節的 Error Schema 格式）。
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..schemas.common import ErrorDetail, ErrorResponse
from ..services import errors

_ERROR_MAP: dict[type[Exception], tuple[int, str]] = {
    errors.VideoNotFoundError: (404, "VIDEO_NOT_FOUND"),
    errors.DuplicateJobError: (409, "DUPLICATE_JOB"),
    errors.DurationLimitExceededError: (422, "DURATION_LIMIT_EXCEEDED"),
    errors.InvalidUrlError: (400, "INVALID_URL"),
    errors.JobNotFoundError: (404, "JOB_NOT_FOUND"),
    errors.InvalidJobStateError: (409, "INVALID_JOB_STATE"),
    errors.ConversationNotFoundError: (404, "CONVERSATION_NOT_FOUND"),
    # 這兩個對前端是正常狀態不是錯誤（用 404 區分「還沒整理／產不出縮圖」與
    # 「有內容」），但回應形狀跟其他 404 相同，所以一併走這張表，不讓端點各自
    # 手刻 JSONResponse，見 services/errors.py 的說明。
    errors.DocumentNotFoundError: (404, "DOCUMENT_NOT_FOUND"),
    errors.ThumbnailUnavailableError: (404, "THUMBNAIL_UNAVAILABLE"),
    # 422 而不是 404：影片存在（404 已經由 VideoNotFoundError 表達過了），是
    # 「這一秒抽不出畫面」——使用者送出的請求本身沒辦法被滿足。
    errors.FrameUnavailableError: (422, "FRAME_UNAVAILABLE"),
    # 502：失敗的是上游的 YouTube／yt-dlp，不是使用者的請求有問題。
    errors.YoutubeSearchError: (502, "YOUTUBE_SEARCH_FAILED"),
}


def install_exception_handlers(app: FastAPI) -> None:
    for exc_type, (status_code, code) in _ERROR_MAP.items():
        app.add_exception_handler(exc_type, _make_handler(status_code, code))


def _make_handler(status_code: int, code: str):
    async def _handler(_request: Request, exc: Exception) -> JSONResponse:
        # 用 schemas/common.py 的模型建 body，不是手打 dict 字面值：那兩個模型
        # 本來就是為了描述這個形狀而存在的，但在這之前全專案沒有任何地方 import
        # 它們——形狀的「規格」與「實作」是分開的兩份，改一邊不會有人提醒。
        body = ErrorResponse(error=ErrorDetail(code=code, message=str(exc), details=None))
        return JSONResponse(status_code=status_code, content=body.model_dump())

    return _handler
