"""共用的抽幀工具：用 ffmpeg 從影片指定時間點抽出單張畫面。
VLM（vlm.py）與本地 OCR（ocr_service.py）都需要「在時間點 T 抽一張畫面」，
拉成共用模組避免重複實作。

子行程呼叫與暫存檔本身走 media.py；這裡只留「抽一張畫面」這個決定
（`-ss` 放在 `-i` 之前、JPEG 品質 3）。
"""
from __future__ import annotations

from pathlib import Path

from . import media


def extract_frame(video_path: Path, at_sec: float) -> Path:
    """在指定時間點抽一張畫面，回傳暫存 JPEG 檔路徑；呼叫端負責用完後刪除。"""
    frame_path = media.new_temp_path(".jpg")
    media.run_ffmpeg(
        [
            # -ss 在 -i 之前＝快速 seek（先跳再解碼），順序不能調換
            "-ss", str(max(at_sec, 0.0)), "-i", str(video_path),
            "-frames:v", "1", "-q:v", "3",
            str(frame_path),
        ],
        timeout=media.FRAME_TIMEOUT_SEC,
    )
    return frame_path
