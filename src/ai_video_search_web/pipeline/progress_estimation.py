"""共用的「背景執行緒＋預估進度」邏輯：包住一個沒有原生進度回報的耗時工作
（PySceneDetect、Whisper API 都沒有提供逐步進度），在背景執行緒跑，主執行緒
同時依呼叫端算好的預估總時間，定期回報百分比。

scene_detect.py 與 asr.py 原本各自獨立實作了幾乎一樣的這段邏輯（重構前
逐行比對過，除了「被包住的耗時工作」不同，其餘結構幾乎逐字重複），這裡
抽出共用，兩邊都改呼叫這個模組。
"""
from __future__ import annotations

import threading
import time
from typing import Callable, TypeVar

T = TypeVar("T")

MAX_DISPLAY_PERCENT = 95
POLL_INTERVAL_SEC = 0.4


def run_with_estimated_progress(
    work: Callable[[], T],
    estimated_total_sec: float,
    on_progress: Callable[[int], None] | None = None,
) -> T:
    """在背景執行緒跑 work()，主執行緒同時依 estimated_total_sec 定期回報預估
    百分比（上限 MAX_DISPLAY_PERCENT——預估值不準，讓它跑到 100% 但工作還沒
    完成會讓使用者誤以為卡住，所以留在 95% 等真正完成才跳 100%）。work() 拋出
    的例外會在這裡重新拋出，呼叫端可以正常用 try/except 處理，不需要知道
    背後是背景執行緒在跑。
    """
    outcome: dict[str, object] = {}

    def _call() -> None:
        try:
            outcome["result"] = work()
        except Exception as exc:  # 記錄例外，讓外層 join 後在主執行緒重新拋出
            outcome["error"] = exc

    thread = threading.Thread(target=_call, daemon=True)
    start = time.time()
    thread.start()

    while thread.is_alive():
        elapsed = time.time() - start
        percent = min(MAX_DISPLAY_PERCENT, round(elapsed / estimated_total_sec * 100))
        if on_progress is not None:
            on_progress(percent)
        thread.join(timeout=POLL_INTERVAL_SEC)

    if "error" in outcome:
        raise outcome["error"]  # type: ignore[misc]
    return outcome["result"]  # type: ignore[return-value]
