"""搜尋 Application Service：薄包裝 pipeline.search.search()。

存在的理由是讓 api/ 只依賴 services/，不直接依賴 pipeline/，
見 docs/09-web-ui-migration-plan.md。
"""
from __future__ import annotations

from ..pipeline import search as search_pipeline
from ..pipeline.search import SearchResponse, SearchResult

__all__ = ["SearchResponse", "SearchResult", "search"]


def search(query: str, video_id: int | None = None, top_k: int = 20) -> SearchResponse:
    return search_pipeline.search(query, top_k=top_k, video_id=video_id)
