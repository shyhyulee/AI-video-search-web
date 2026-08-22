"""共用的抽幀工具：用 ffmpeg 從影片指定時間點抽出單張畫面。
VLM（vlm.py）與本地 OCR（ocr_service.py）都需要「在時間點 T 抽一張畫面」，
拉成共用模組避免重複實作。
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


def extract_frame(video_path: Path, at_sec: float) -> Path:
    """在指定時間點抽一張畫面，回傳暫存 JPEG 檔路徑；呼叫端負責用完後刪除。"""
    fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    frame_path = Path(tmp_path)
    subprocess.run(
        [
            "ffmpeg", "-y", "-ss", str(max(at_sec, 0.0)), "-i", str(video_path),
            "-frames:v", "1", "-q:v", "3",
            str(frame_path),
        ],
        check=True,
        capture_output=True,
    )
    return frame_path
