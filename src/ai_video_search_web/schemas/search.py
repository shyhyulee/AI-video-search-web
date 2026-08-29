from __future__ import annotations

import dataclasses

from pydantic import BaseModel

from ..pipeline.search import SearchResult


class SearchRequest(BaseModel):
    query: str
    # 搜尋範圍：省略／null 代表搜全部影片，給一組 id 就只搜那幾支。刻意不另外
    # 保留單數的 video_id 欄位——兩個欄位並存就會需要一條「哪個優先」的隱形
    # 規則，單支影片直接送長度 1 的 list 即可。
    video_ids: list[int] | None = None
    top_k: int = 20


class SearchResultOut(BaseModel):
    segment_id: int
    video_id: int
    video_title: str
    start_sec: float
    end_sec: float
    similarity: float
    hit_source: str
    description: str
    transcript: str | None
    transcript_score: float | None
    visual_score: float | None
    ocr_score: float | None
    fusion_strategy: str
    fusion_score: float

    @classmethod
    def from_result(cls, result: SearchResult) -> "SearchResultOut":
        return cls(**dataclasses.asdict(result))


class SearchResponseOut(BaseModel):
    results: list[SearchResultOut]
    cost_usd: float
    is_confident: bool
