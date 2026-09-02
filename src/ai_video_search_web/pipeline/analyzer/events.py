"""分析執行緒送進 progress_queue 的三種事件——這是 analyzer 與 job_manager
之間的契約，兩邊都只認這三個 dataclass。

放在最底層（不 import 套件內任何東西）：context 要送進度、worker 要送終端事件，
兩者都依賴它，它不依賴任何人。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AnalysisProgress:
    stage: str
    detail: str = ""


@dataclass
class AnalysisResult:
    video_id: int
    segment_count: int
    cost_usd: float
    partial: bool
    vlm_failed_count: int = 0


@dataclass
class AnalysisError:
    video_id: int
    message: str
