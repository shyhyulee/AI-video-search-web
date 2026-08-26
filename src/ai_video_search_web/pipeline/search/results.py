"""搜尋結果的資料形狀：SearchResult／SearchResponse，以及「命中來源」文字。

排序（RRF 融合分數）跟 `similarity` 欄位是分開的兩件事：`similarity` 保留
原本的 dense cosine 分數語意（UI 拿來畫百分比／進度條，見
docs/AI_Video_Search_搜尋準確率提升規劃.md 的「保留現有 UI 操作」原則），
RRF 只決定 `results` 的排列順序，不覆寫這個欄位。`SearchResult.fusion_score`
額外把 RRF 分數本身也帶出來，讓呼叫端在需要時能解釋排序依據（Web UI 曾經
顯示過這個數字，見 docs/11 §8.13 已移除，欄位本身保留）。
"""
from __future__ import annotations

from dataclasses import dataclass

FUSION_STRATEGY = (
    "RRF 融合（dense cosine 相似度 + BM25 關鍵字；查詢已翻譯成中英文各自比對取最高分）"
)

_MODALITY_NAMES = {"transcript": "字幕", "visual": "畫面", "ocr": "OCR"}
_MODALITY_ORDER = ("transcript", "visual", "ocr")
_CLOSE_THRESHOLD = 0.03


@dataclass
class SearchResult:
    segment_id: int  # 對應 db.SegmentRecord.id，供多輪對話跨輪次穩定引用同一個片段
    video_id: int
    video_title: str
    start_sec: float
    end_sec: float
    similarity: float
    hit_source: str  # 字幕 / 畫面 / 字幕＋畫面
    description: str
    transcript: str | None
    transcript_score: float | None
    visual_score: float | None
    ocr_score: float | None
    fusion_strategy: str
    fusion_score: float = 0.0  # RRF 融合分數，排序依據；search() 算完 fused_scores 後才填入


@dataclass
class SearchResponse:
    results: list[SearchResult]
    cost_usd: float
    is_confident: bool  # top1 是否同時被 sparse channel 印證，見套件說明


def _hit_source(
    transcript_score: float | None, visual_score: float | None, ocr_score: float | None
) -> str:
    """依規格「字幕｜畫面｜OCR｜字幕＋畫面｜綜合」：只有一個模態命中就顯示該模態；
    兩個模態分數相近（差距 < 0.03）就顯示組合名稱；三個都相近就顯示「綜合」。
    """
    available = {
        "transcript": transcript_score,
        "visual": visual_score,
        "ocr": ocr_score,
    }
    available = {k: v for k, v in available.items() if v is not None}
    if not available:
        return "畫面"  # 理論上不會發生：search() 已過濾掉三個模態都沒有分數的片段

    max_score = max(available.values())
    close = [k for k in _MODALITY_ORDER if k in available and max_score - available[k] < _CLOSE_THRESHOLD]

    if len(close) >= 3:
        return "綜合"
    return "＋".join(_MODALITY_NAMES[k] for k in close)
