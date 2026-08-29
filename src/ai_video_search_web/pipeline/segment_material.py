"""把片段攤成餵給 LLM 的逐行素材：`[MM:SS] 畫面：…；字幕：…；畫面文字：…`。

summary.py（影片摘要）與 document.py（結構化文件）本來各有一份幾乎相同的實作，
連 `_format_timestamp()` 都是逐字重複的。兩者的 prompt 目的不同，但「素材長什麼
樣子」是同一個決定——時間戳格式、欄位標籤、分隔符號、沒有任何內容的片段要略過
——改其中一邊而忘了另一邊，兩個功能餵給模型的素材就會悄悄長得不一樣。

只留一個開關 `include_ocr`：文件會帶畫面文字、摘要不帶。這是實測逼出來的差異
（1,076/1,156 個片段有畫面文字，對流程類影片特別有價值，摘要用不到但 SOP 用得
到），不是可有可無的選項。

**截斷不在這裡**：summary.py 只取前 200 段（prompt 長度控制），document.py 刻意
不截斷（SOP 少掉尾段等於少掉最後幾個製程步驟，比直接失敗更糟）。這是兩邊各自的
決定，留在各自的呼叫端才看得見。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..db import SegmentRecord

# VLM 偶爾會把「沒有畫面文字」寫成字面字串而不是 JSON null（實測全庫 1,156 個
# 片段裡有 21 個這樣），不濾掉就會餵一堆 "null" 給 LLM 當畫面文字。
_PLACEHOLDER_TEXTS = {"null", "none", "n/a", "na", "無", "-"}


def format_timestamp(sec: float) -> str:
    """秒數轉成 `MM:SS`。超過 60 分鐘不會進位成 HH:MM:SS——分析長度上限是
    1 小時（見 analyzer.MAX_DURATION_SEC），所以 MM 最多兩位數。"""
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def build_material(segments: "list[SegmentRecord]", *, include_ocr: bool = False) -> str:
    """把片段依時間順序攤成逐行素材；三個欄位都是空的片段整行略過。"""
    lines = []
    for seg in segments:
        parts = []
        if _clean(seg.visual_description):
            parts.append(f"畫面：{_clean(seg.visual_description)}")
        if _clean(seg.transcript):
            parts.append(f"字幕：{_clean(seg.transcript)}")
        if include_ocr and _clean(seg.ocr_text):
            parts.append(f"畫面文字：{_clean(seg.ocr_text)}")
        if parts:
            lines.append(f"[{format_timestamp(seg.start_sec)}] " + "；".join(parts))
    return "\n".join(lines)


def _clean(text: str | None) -> str:
    """去掉前後空白，並把 VLM 偶爾產生的字面佔位字串當成空值。"""
    stripped = (text or "").strip()
    return "" if stripped.lower() in _PLACEHOLDER_TEXTS else stripped
