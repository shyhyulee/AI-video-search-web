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


def has_audio_stream(video_path: Path) -> bool:
    """這支影片有沒有音軌。

    兩個用途，都在 analyzer：**跳過沒有意義的 ASR 呼叫**（Whisper 按分鐘計價、
    實測佔一支影片總成本的 62～66%），以及**避免整支分析失敗**——`asr._extract_audio()`
    對沒有音軌的檔案會讓 ffmpeg 以「Output file does not contain any stream」
    失敗，而 ASR 例外會讓整支分析失敗（不是略過字幕），所以在沒有這道檢查之前，
    一支純畫面的影片根本分析不完。

    讀不到就回 True（當作有音軌）：猜錯的代價不對稱——當成沒有音軌會讓一支
    真的有旁白的影片整支失去字幕，當成有音軌最多只是白花一次 ASR 的錢。
    """
    try:
        codec = run_ffprobe(
            [
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_type",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ]
        )
    except (subprocess.SubprocessError, OSError):
        return True
    return codec == "audio"


def run_ffprobe(args: list[str], *, timeout: float = FFPROBE_TIMEOUT_SEC) -> str:
    """跑一次 ffprobe，回傳標準輸出（已 strip）。`args` 不含 `ffprobe -v error`
    前綴。失敗一律拋例外，兩個呼叫端各自決定怎麼退回。
    """
    result = subprocess.run(
        ["ffprobe", "-v", "error", *args],
        capture_output=True, text=True, timeout=timeout, check=True,
    )
    return result.stdout.strip()
