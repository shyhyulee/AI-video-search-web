from __future__ import annotations

import dataclasses

from pydantic import BaseModel

from ..pipeline.search import SearchResult


class SearchRequest(BaseModel):
    query: str
    video_id: int | None = None
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
