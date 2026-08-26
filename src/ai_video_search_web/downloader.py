"""YouTube 影片下載：包裝 yt-dlp，在背景執行緒下載並透過 Queue 回報進度。

呼叫端（services/job_manager.py）負責讀走 Queue 事件並寫進 jobs 表；
本模組不碰資料庫、也不知道 job 的存在，維持執行緒安全。
"""
from __future__ import annotations

import logging
import queue
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from .db import PROJECT_ROOT

logger = logging.getLogger(__name__)

VIDEO_DIR = PROJECT_ROOT / "video"

# POC 階段固定 720p：畫質足夠讓後續 VLM 判斷畫面內容，同時控制下載時間與硬碟空間。
QUALITY_FORMAT = "bestvideo[height<=720]+bestaudio/best[height<=720]/best[height<=720]"

_YOUTUBE_URL_RE = re.compile(r"(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)")


def is_youtube_url(url: str) -> bool:
    return bool(_YOUTUBE_URL_RE.search(url.strip()))


@dataclass
class DownloadProgress:
    status: str  # "downloading" / "error"
    percent: float = 0.0
    speed_text: str = ""
    eta_text: str = ""
    title: str = ""
    error_message: str = ""


@dataclass
class DownloadResult:
    title: str
    file_path: Path
    duration_sec: int | None


def start_download(
    url: str, progress_queue: "queue.Queue[object]", dest_dir: Path | None = None
) -> threading.Thread:
    """啟動背景執行緒下載，立即回傳、不阻塞呼叫端。dest_dir 預設為 VIDEO_DIR；
    Web 版 Job Manager 會傳入依 job_id 區隔的子目錄，避免不同 URL 剛好標題
    相同時互相覆蓋檔案，見 docs/09-web-ui-migration-plan.md 3.1 節。
    """
    thread = threading.Thread(target=_download_worker, args=(url, progress_queue, dest_dir), daemon=True)
    thread.start()
    return thread


def _download_worker(
    url: str, progress_queue: "queue.Queue[object]", dest_dir: Path | None = None
) -> None:
    target_dir = dest_dir if dest_dir is not None else VIDEO_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    def hook(status: dict) -> None:
        if status.get("status") != "downloading":
            return
        total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
        downloaded = status.get("downloaded_bytes") or 0
        percent = (downloaded / total * 100) if total else 0.0
        progress_queue.put(
            DownloadProgress(
                status="downloading",
                percent=percent,
                speed_text=_format_speed(status.get("speed")),
                eta_text=_format_eta(status.get("eta")),
                title=(status.get("info_dict") or {}).get("title", ""),
            )
        )

    options = {
        "format": QUALITY_FORMAT,
        "merge_output_format": "mp4",
        "outtmpl": str(target_dir / "%(title)s.%(ext)s"),
        "progress_hooks": [hook],
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        # YouTube 近期要求 PO Token 才能對多數 client 的實際影片資料發出請求，
        # 否則即使抓得到 metadata，實際下載也會 403；web_embedded 這個 client
        # 目前不需要 PO Token，但仍需要 JS runtime 解出簽章挑戰。
        "js_runtimes": {"node": {}},
        "extractor_args": {"youtube": {"player_client": ["web_embedded"]}},
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
            result = DownloadResult(
                title=info.get("title") or file_path.stem,
                file_path=file_path,
                duration_sec=info.get("duration"),
            )
        progress_queue.put(result)
    except Exception as exc:  # yt-dlp 例外種類很多，統一攔截並回報給畫面
        logger.error("下載失敗：%s｜%s", url, exc, exc_info=True)
        progress_queue.put(DownloadProgress(status="error", error_message=str(exc)))


def _format_speed(bytes_per_sec: float | None) -> str:
    if not bytes_per_sec:
        return "--"
    return f"{bytes_per_sec / 1024 / 1024:.1f} MB/s"


def _format_eta(seconds: int | None) -> str:
    if not seconds:
        return "--"
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"
