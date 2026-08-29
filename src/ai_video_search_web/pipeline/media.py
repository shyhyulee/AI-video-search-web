"""ffmpeg／ffprobe 子行程呼叫與暫存檔管理，五個呼叫端共用。

抽出來的理由不只是「少寫幾行」：原本五個呼叫端各自決定要不要設 timeout，
結果 `frames.extract_frame()` 與 `asr._extract_audio()` **沒有設**——ffmpeg
真的卡住時（損毀的檔案、掛掉的網路磁碟）那條分析執行緒會無限期停在
`subprocess.run()`，analyzer 送不出終端事件，job_manager 的分析 slot 就再也
不會釋放，**之後每一支影片的分析都會卡在 queued，只能重啟伺服器**（跟第三輪
C0 修掉的那個缺陷是同一條失敗路徑）。timeout 現在是這裡的必填參數，不是每個
呼叫端各自記得要加的東西。

超時的處理沿用各呼叫端既有的失敗語意，不在這裡統一：`subprocess.TimeoutExpired`
是 `SubprocessError` 的子類別，所以本來就會吞例外的呼叫端（縮圖、ffprobe 兩處）
照樣吞掉，本來就往外拋的（抽幀、抽音訊）照樣往外拋。

命令列的共同前綴（`ffmpeg -y`／`ffprobe -v error`）也收在這裡，讓「所有 ffmpeg
呼叫都覆寫輸出檔、所有 ffprobe 呼叫都只印錯誤」變成一個決定而不是五個。
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

#: 抽單張畫面（縮圖與 VLM／OCR 抽幀）。`-ss` 放在 `-i` 前面是快速 seek，
#: 正常情況是次秒級；15 秒是既有縮圖擷取實際用了一段時間沒出問題的值。
FRAME_TIMEOUT_SEC = 15.0

#: 抽整支影片的音訊。比抽幀寬得多——它要讀完整個檔案，而分析長度上限是
#: 1 小時（見 analyzer.MAX_DURATION_SEC）。
AUDIO_TIMEOUT_SEC = 300.0

#: ffprobe 只讀 metadata，不解碼；兩個既有呼叫端本來就都用 10 秒。
FFPROBE_TIMEOUT_SEC = 10.0


def new_temp_path(suffix: str) -> Path:
    """建立一個空的暫存檔並回傳路徑，**呼叫端負責刪除**。

    不做成 context manager：三個呼叫端裡有兩個（抽幀、抽音訊）是把路徑回傳給
    更外層，暫存檔的壽命比產生它的函式長，context manager 反而套不上。
    """
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)  # 只要路徑，實際寫入交給 ffmpeg
    return Path(path)


def run_ffmpeg(args: list[str], *, timeout: float) -> None:
    """跑一次 ffmpeg。`args` 不含 `ffmpeg -y` 前綴。

    timeout 是關鍵字參數而且沒有預設值：不同操作的合理上限差了一個數量級
    （抽一張畫面 vs 讀完一小時的影片），給預設值只會讓呼叫端不去想這件事。
    失敗（非 0 return code 或超時）一律拋例外，要不要吞由呼叫端決定。
    """
    subprocess.run(["ffmpeg", "-y", *args], check=True, capture_output=True, timeout=timeout)


def run_ffprobe(args: list[str], *, timeout: float = FFPROBE_TIMEOUT_SEC) -> str:
    """跑一次 ffprobe，回傳標準輸出（已 strip）。`args` 不含 `ffprobe -v error`
    前綴。失敗一律拋例外，兩個呼叫端各自決定怎麼退回。
    """
    result = subprocess.run(
        ["ffprobe", "-v", "error", *args],
        capture_output=True, text=True, timeout=timeout, check=True,
    )
    return result.stdout.strip()
