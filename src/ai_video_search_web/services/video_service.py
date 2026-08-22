"""影片相關的 Application Service：包裝 db.videos／downloader／analyzer 的呼叫，
供 Tkinter UI（Phase 1）與之後的 FastAPI（Phase 2）共用，見
docs/09-web-ui-migration-plan.md。這一層目前是純透傳包裝，不改變任何既有行為，
只是把 ui/*_tab.py 原本直接呼叫 db.*／pipeline.* 的地方集中到這裡；下載／分析
本身（downloader.start_download／analyzer.start_analysis）仍由呼叫端直接呼叫，
不在這裡包裝，見計畫文件 4.2 節。
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from .. import db, downloader
from ..pipeline import analyzer, summary as summary_pipeline
from ..pipeline.openai_client import get_client

logger = logging.getLogger(__name__)

_THUMBNAIL_SIZE = (320, 180)


def is_youtube_url(url: str) -> bool:
    return downloader.is_youtube_url(url)


def find_existing_by_url(source_url: str) -> db.VideoRecord | None:
    return db.find_by_source_url(source_url)


def register_downloaded_video(
    title: str, source_url: str, file_path: Path, duration_sec: int | None
) -> int:
    return db.insert_video(
        title=title,
        source=db.SOURCE_YOUTUBE,
        source_url=source_url,
        file_path=str(file_path),
        duration_sec=duration_sec,
    )


def probe_local_duration(video_path: Path) -> int | None:
    """用 ffprobe 讀取本機影片長度；讀不到就回傳 None，不擋住新增流程。"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video_path)],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return round(float(result.stdout.strip()))
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


def register_local_video(path: Path, duration_sec: int | None) -> int:
    return db.insert_video(
        title=path.stem,
        source=db.SOURCE_LOCAL,
        source_url=None,
        file_path=str(path),
        duration_sec=duration_sec,
    )


def register_uploaded_video(title: str, file_path: Path, duration_sec: int | None) -> int:
    """跟 register_local_video() 的差別：Web 上傳情境下磁碟檔名是系統產生的
    uuid（避免 Path Traversal／檔名衝突，見 api/videos.py 上傳端點），跟
    使用者看到的標題是兩件事，標題要由呼叫端另外傳入，不能沿用 file_path.stem。
    """
    return db.insert_video(
        title=title,
        source=db.SOURCE_LOCAL,
        source_url=None,
        file_path=str(file_path),
        duration_sec=duration_sec,
    )


def list_pending_videos() -> list[db.VideoRecord]:
    return db.list_pending_videos()


def list_library_videos() -> list[db.VideoRecord]:
    return db.list_library_videos()


def get_video(video_id: int) -> db.VideoRecord | None:
    return db.get_video(video_id)


def list_segments_for_video(video_id: int) -> list[db.SegmentRecord]:
    return db.list_segments_for_video(video_id)


def is_within_duration_limit(duration_sec: int | None) -> bool:
    return analyzer.is_within_duration_limit(duration_sec)


def max_duration_minutes() -> int:
    return analyzer.MAX_DURATION_SEC // 60


def delete_video(video_id: int) -> tuple[db.VideoRecord | None, str | None]:
    """刪除影片 DB 紀錄與磁碟檔案。回傳 (被刪除的紀錄或 None, 檔案刪除失敗時的
    錯誤訊息或 None)。檔案刪除失敗會記錄完整 log（含 traceback），但不影響 DB
    紀錄已刪除的事實；錯誤訊息文字交給呼叫端決定如何呈現（Tkinter 用
    messagebox，之後 API 版本可以轉成錯誤回應）。
    """
    record = db.delete_video(video_id)
    if record is None:
        return None, None
    file_path = Path(record.file_path)
    try:
        file_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.error(
            f"「{record.title}」的檔案刪除失敗：{exc}",
            exc_info=True,
            extra={"video_title": record.title, "pipeline_stage": "刪除檔案"},
        )
        return record, str(exc)
    return record, None


def reset_to_pending(video_id: int) -> None:
    db.reset_to_pending(video_id)


def regenerate_summary(video_id: int, segments: list[db.SegmentRecord]) -> summary_pipeline.SummaryResult:
    client = get_client()
    result = summary_pipeline.generate_summary(client, segments)
    db.update_video_summary(video_id, result.summary, summary_pipeline.MODEL_NAME, result.cost_usd)
    return result


def generate_thumbnail(video: db.VideoRecord, size: tuple[int, int] = _THUMBNAIL_SIZE) -> bytes | None:
    """在影片時間中點用 ffmpeg 擷取一張縮圖，回傳 PNG bytes；擷取失敗回傳
    None。每次呼叫都重新產生（沿用桌面版 library_tab.py 目前的即時產生行為，
    尚未做 docs/09-web-ui-migration-plan.md Phase 3 規劃的「分析完成時就
    產生並保存」，那項是 Web 版 UI 上線時才需要的最佳化，這裡先提供 API
    能力本身）。
    """
    if not video.file_path or not Path(video.file_path).exists():
        return None

    mid_sec = (video.duration_sec or 0) / 2
    fd, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    thumb_path = Path(tmp_path)
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-ss", str(max(mid_sec, 0.0)), "-i", video.file_path,
                "-vf", f"scale={size[0]}:{size[1]}",
                "-frames:v", "1",
                str(thumb_path),
            ],
            check=True, capture_output=True, timeout=15,
        )
        return thumb_path.read_bytes()
    except (subprocess.SubprocessError, OSError):
        return None
    finally:
        thumb_path.unlink(missing_ok=True)
