"""搜尋 API，見 docs/09-web-ui-migration-plan.md。"""
from __future__ import annotations

from fastapi import APIRouter

from ..schemas.search import SearchRequest, SearchResponseOut, SearchResultOut
from ..services import search_service

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponseOut)
def search(payload: SearchRequest) -> SearchResponseOut:
    response = search_service.search(payload.query, video_ids=payload.video_ids, top_k=payload.top_k)
    return SearchResponseOut(
        results=[SearchResultOut.from_result(r) for r in response.results],
        cost_usd=response.cost_usd,
        is_confident=response.is_confident,
    )
