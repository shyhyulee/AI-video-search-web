"""影片相關 API：CRUD、上傳、YouTube 下載觸發、分析／重新分析／摘要觸發、
串流與縮圖。見 docs/09-web-ui-migration-plan.md 4.3 節。

/upload 只接受瀏覽器上傳的檔案內容，不接受使用者本機路徑字串——瀏覽器本來
就只能這樣做（Browser 只能上傳檔案內容，不能把使用者本機路徑交給後端使用），
跟 Tkinter 版 filedialog 選本機檔案是不同情境，不是同一段邏輯的搬遷。
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from .. import db, downloader
from ..schemas.jobs import JobOut
from ..schemas.videos import VideoOut, YoutubeDownloadRequest
from ..services import job_manager, video_service

router = APIRouter(prefix="/videos", tags=["videos"])

_ALLOWED_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}


@router.get("", response_model=list[VideoOut])
def list_videos(status: str | None = None) -> list[VideoOut]:
    records = video_service.list_pending_videos() if status == "pending" else video_service.list_library_videos()
    return [VideoOut.from_record(v, video_service.list_segments_for_video(v.id)) for v in records]


@router.get("/{video_id}", response_model=VideoOut)
def get_video(video_id: int) -> VideoOut:
    video = video_service.get_video(video_id)
    if video is None:
        raise job_manager.VideoNotFoundError(f"找不到影片 {video_id}")
    return VideoOut.from_record(video, video_service.list_segments_for_video(video_id))


@router.delete("/{video_id}")
def delete_video(video_id: int) -> dict[str, bool]:
    record, _file_error = video_service.delete_video(video_id)
    if record is None:
        raise job_manager.VideoNotFoundError(f"找不到影片 {video_id}")
    return {"deleted": True}


@router.post("/upload", response_model=VideoOut, status_code=201)
def upload_video(file: UploadFile) -> VideoOut:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=422, detail=f"不支援的檔案格式：{suffix or '（無副檔名）'}")

    upload_dir = downloader.VIDEO_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    # 用系統產生的檔名（uuid4），不沿用使用者上傳的檔名，避免 Path Traversal
    # 與覆蓋檔案，見 docs/08-web-ui-migration-design.md 第 11 節。
    dest_path = upload_dir / f"{uuid.uuid4().hex}{suffix}"
    with dest_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    duration_sec = video_service.probe_local_duration(dest_path)
    title = Path(file.filename or dest_path.name).stem
    video_id = video_service.register_uploaded_video(title, dest_path, duration_sec)
    video = video_service.get_video(video_id)
    assert video is not None
    return VideoOut.from_record(video)


@router.post("/youtube", response_model=JobOut, status_code=202)
def download_youtube_video(payload: YoutubeDownloadRequest) -> JobOut:
    job_id = job_manager.submit_download(payload.url)
    job = db.get_job(job_id)
    assert job is not None
    return JobOut.from_record(job)


@router.post("/{video_id}/analyze", response_model=JobOut, status_code=202)
def analyze_video(video_id: int) -> JobOut:
    job_id = job_manager.submit_analysis(video_id)
    job = db.get_job(job_id)
    assert job is not None
    return JobOut.from_record(job)


@router.post("/{video_id}/reanalyze", response_model=JobOut, status_code=202)
def reanalyze_video(video_id: int) -> JobOut:
    video = video_service.get_video(video_id)
    if video is None:
        raise job_manager.VideoNotFoundError(f"找不到影片 {video_id}")
    video_service.reset_to_pending(video_id)
    job_id = job_manager.submit_analysis(video_id)
    job = db.get_job(job_id)
    assert job is not None
    return JobOut.from_record(job)


@router.post("/{video_id}/summary", response_model=VideoOut)
def regenerate_summary(video_id: int) -> VideoOut:
    segments = video_service.list_segments_for_video(video_id)
    if not segments:
        raise HTTPException(status_code=422, detail="這支影片還沒有任何分析片段，無法產生摘要")
    video_service.regenerate_summary(video_id, segments)
    video = video_service.get_video(video_id)
    assert video is not None
    return VideoOut.from_record(video, segments)


@router.get("/{video_id}/stream")
def stream_video(video_id: int) -> FileResponse:
    video = video_service.get_video(video_id)
    if video is None:
        raise job_manager.VideoNotFoundError(f"找不到影片 {video_id}")
    return FileResponse(video.file_path, media_type="video/mp4")


@router.get("/{video_id}/thumbnail")
def get_thumbnail(video_id: int) -> Response:
    video = video_service.get_video(video_id)
    if video is None:
        raise job_manager.VideoNotFoundError(f"找不到影片 {video_id}")
    thumbnail = video_service.generate_thumbnail(video)
    if thumbnail is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "THUMBNAIL_UNAVAILABLE", "message": "無法產生縮圖", "details": None}},
        )
    return Response(content=thumbnail, media_type="image/png")
