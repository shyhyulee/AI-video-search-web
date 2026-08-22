"""共用的片段播放邏輯：search_tab.py／conversation_tab.py 都需要「用 ffplay
播放某個影片片段」，抽成共用函式避免重複實作同一段 subprocess 呼叫與例外處理。
"""
from __future__ import annotations

import logging
import subprocess
from tkinter import messagebox

from .. import db

logger = logging.getLogger(__name__)


def play_segment(video_id: int, video_title: str, start_sec: float, end_sec: float) -> None:
    """查出影片檔案路徑並用 ffplay 播放指定時間區間；找不到影片或啟動播放器
    失敗都用訊息框提示，不讓例外往外拋出去干擾呼叫端的事件迴圈。"""
    video = db.get_video(video_id)
    if video is None:
        messagebox.showwarning("播放失敗", "找不到這支影片的紀錄")
        return

    duration = max(end_sec - start_sec, 0.5)
    try:
        subprocess.Popen(
            [
                "ffplay", "-autoexit", "-loglevel", "error",
                "-ss", str(start_sec), "-t", str(duration),
                video.file_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        logger.error(
            f"「{video_title}」播放失敗：{exc}",
            exc_info=True,
            extra={"video_title": video_title, "pipeline_stage": "播放"},
        )
        messagebox.showwarning("播放失敗", f"無法啟動播放器：{exc}")
