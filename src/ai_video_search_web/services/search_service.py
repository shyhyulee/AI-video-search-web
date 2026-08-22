"""搜尋 Application Service：薄包裝 pipeline.search.search()，供 Tkinter UI
（Phase 1）與之後的 FastAPI（Phase 2）共用，見 docs/09-web-ui-migration-plan.md。
"""
from __future__ import annotations

from ..pipeline import search as search_pipeline
from ..pipeline.search import SearchResponse, SearchResult

__all__ = ["SearchResponse", "SearchResult", "search"]


def search(query: str, video_id: int | None = None, top_k: int = 20) -> SearchResponse:
    return search_pipeline.search(query, top_k=top_k, video_id=video_id)
