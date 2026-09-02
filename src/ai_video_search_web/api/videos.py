"""影片相關 API：CRUD、上傳、YouTube 下載觸發、分析／重新分析／摘要觸發、
串流與縮圖。見 docs/09-web-ui-migration-plan.md 4.3 節。

/upload 只接受瀏覽器上傳的檔案內容，不接受使用者本機路徑字串——瀏覽器本來
就只能這樣做。注意前端已經沒有呼叫這個端點（本機上傳在 docs/11 §8.5 移除），
端點與測試保留著。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from ..schemas.jobs import JobOut
from ..schemas.videos import (
    FrameQAOut,
    FrameQARequest,
    VideoDocumentOut,
    VideoOut,
    YoutubeDownloadRequest,
)
from ..services import job_manager, video_service
from ..services.errors import DocumentNotFoundError, ThumbnailUnavailableError, VideoNotFoundError

router = APIRouter(prefix="/videos", tags=["videos"])

_ALLOWED_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}


def _get_video_or_raise(video_id: int) -> video_service.VideoRecord:
    """讀影片，找不到就丟 VideoNotFoundError（統一對映成 404）。原本每個端點
    各自 `if video is None: raise ...`，或在「剛寫進去、理論上一定讀得到」的
    地方用 assert——assert 在 `python -O` 下會整個消失。"""
    video = video_service.get_video(video_id)
    if video is None:
        raise VideoNotFoundError(f"找不到影片 {video_id}")
    return video


@router.get("", response_model=list[VideoOut])
def list_videos(status: str | None = None) -> list[VideoOut]:
    # `status=pending` ＝「影片分析」頁的清單，包含 pending 與 analyzing 兩種
    # 狀態（查詢字串沿用 pending 這個值，語意是「還沒進影片庫」）；不給 status
    # ＝「影片庫」的 analyzed／failed。分析中的影片一定要留在前者，否則會在整段
    # 分析期間從兩個頁籤同時消失，見 db.list_unanalyzed_videos()。
    records = video_service.list_unanalyzed_videos() if status == "pending" else video_service.list_library_videos()
    # 三個模態旗標一次聚合查完，不要逐支影片載入全部 segment（那會連 embedding
    # BLOB 一起讀出來，只為了算三個布林值）。
    flags = video_service.modality_flags([v.id for v in records])
    return [VideoOut.from_record(v, flags.get(v.id)) for v in records]


@router.get("/{video_id}", response_model=VideoOut)
def get_video(video_id: int) -> VideoOut:
    video = _get_video_or_raise(video_id)
    return VideoOut.from_record(video, video_service.modality_flags([video_id]).get(video_id))


@router.delete("/{video_id}")
def delete_video(video_id: int) -> dict[str, bool]:
    record, _file_error = video_service.delete_video(video_id)
    if record is None:
        raise VideoNotFoundError(f"找不到影片 {video_id}")
    return {"deleted": True}


@router.post("/upload", response_model=VideoOut, status_code=201)
def upload_video(file: UploadFile) -> VideoOut:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=422, detail=f"不支援的檔案格式：{suffix or '（無副檔名）'}")

    # 落檔位置與檔名規則（uuid4，防 Path Traversal）在 video_service 裡，
    # 跟刪除影片時 unlink 檔案的那一支放在一起，見 store_upload()。
    dest_path = video_service.store_upload(file.file, suffix)

    duration_sec = video_service.probe_local_duration(dest_path)
    title = Path(file.filename or dest_path.name).stem
    video_id = video_service.register_uploaded_video(title, dest_path, duration_sec)
    video = _get_video_or_raise(video_id)
    return VideoOut.from_record(video)


@router.post("/youtube", response_model=JobOut, status_code=202)
def download_youtube_video(payload: YoutubeDownloadRequest) -> JobOut:
    job_id = job_manager.submit_download(payload.url)
    return JobOut.from_record(job_manager.get_job_or_raise(job_id))


@router.post("/{video_id}/analyze", response_model=JobOut, status_code=202)
def analyze_video(video_id: int) -> JobOut:
    job_id = job_manager.submit_analysis(video_id)
    return JobOut.from_record(job_manager.get_job_or_raise(job_id))


@router.post("/{video_id}/reanalyze", response_model=JobOut, status_code=202)
def reanalyze_video(video_id: int) -> JobOut:
    """重新分析。狀態怎麼切、舊結果什麼時候清，見
    `video_service.prepare_reanalysis()`——重點是分析成功過的影片會留在影片庫
    原地跑完，不會跳去「影片分析」再跳回來，舊片段也還搜得到。"""
    _get_video_or_raise(video_id)
    job_id = job_manager.submit_analysis(video_id, reanalysis=True)
    return JobOut.from_record(job_manager.get_job_or_raise(job_id))


@router.post("/{video_id}/summary", response_model=VideoOut)
def regenerate_summary(video_id: int) -> VideoOut:
    segments = video_service.list_segments_for_video(video_id)
    if not segments:
        raise HTTPException(status_code=422, detail="這支影片還沒有任何分析片段，無法產生摘要")
    video_service.regenerate_summary(video_id, segments)
    video = _get_video_or_raise(video_id)
    return VideoOut.from_record(video, video_service.modality_flags([video_id]).get(video_id))


@router.post("/{video_id}/document", response_model=VideoDocumentOut)
def generate_document(video_id: int) -> VideoDocumentOut:
    """把整支影片整理成一份結構化文件（SOP／教學步驟／課堂筆記／內容紀錄，
    由模型自己依內容判斷），見 pipeline/document.py。

    跟 /reanalyze 不同，這是**同步**端點、不進 jobs 表：單次 LLM 呼叫符合
    docs/09-web-ui-migration-plan.md 的 Category B 判準。代價是回應時間比其他
    同步端點長（輸出 token 比摘要多一個量級），前端要有明確的等待狀態。

    先查影片再查片段，順序跟 /summary 相反是刻意的：那支對不存在的 video_id
    會回 422「沒有分析片段」而不是 404，這裡照 _get_video_or_raise 的慣例做。
    """
    video = _get_video_or_raise(video_id)
    segments = video_service.list_segments_for_video(video_id)
    if not segments:
        raise HTTPException(status_code=422, detail="這支影片還沒有任何分析片段，無法整理成文件")
    result = video_service.generate_document(video, segments)
    return VideoDocumentOut(
        video_id=video_id, document=result.document, model=video_service.document_model_name()
    )


@router.get("/{video_id}/document", response_model=VideoDocumentOut)
def get_document(video_id: int) -> VideoDocumentOut:
    """讀回已經整理好的文件。還沒整理過就是 404——這是正常狀態不是錯誤，
    前端用它來決定要顯示「還沒整理」還是文件內容。"""
    video = _get_video_or_raise(video_id)
    document = video_service.load_document(video)
    if document is None:
        raise DocumentNotFoundError("這支影片還沒有整理過的文件")
    return VideoDocumentOut(video_id=video_id, document=document, model=video.document_model)


@router.get("/{video_id}/stream")
def stream_video(video_id: int) -> FileResponse:
    video = _get_video_or_raise(video_id)
    return FileResponse(video.file_path, media_type="video/mp4")


@router.post("/{video_id}/frame-qa", response_model=FrameQAOut)
def ask_about_frame(video_id: int, payload: FrameQARequest) -> FrameQAOut:
    """對這支影片第 `at_sec` 秒的那一格畫面提問。

    放在 videos 而不是 conversations 底下：它不讀也不寫任何對話狀態，之後要在
    片段搜尋頁或影片庫的觀看模式加同一個功能，直接呼叫這支就好。計畫見
    docs/19-停格畫面問答功能計畫.md。
    """
    video = _get_video_or_raise(video_id)
    result = video_service.answer_about_frame(
        video,
        payload.at_sec,
        payload.question,
        [(turn.question, turn.answer) for turn in payload.history],
    )
    return FrameQAOut(at_sec=payload.at_sec, answer=result.answer, cost_usd=result.cost_usd)


@router.get("/{video_id}/thumbnail")
def get_thumbnail(video_id: int) -> Response:
    video = _get_video_or_raise(video_id)
    thumbnail = video_service.generate_thumbnail(video)
    if thumbnail is None:
        raise ThumbnailUnavailableError("無法產生縮圖")
    return Response(content=thumbnail, media_type="image/png")
