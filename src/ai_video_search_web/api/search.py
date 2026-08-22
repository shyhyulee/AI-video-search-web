"""搜尋 API，見 docs/09-web-ui-migration-plan.md。"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..schemas.search import SearchRequest, SearchResponseOut, SearchResultOut
from ..services import search_service

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponseOut)
def search(payload: SearchRequest) -> SearchResponseOut:
    response = search_service.search(payload.query, video_id=payload.video_id, top_k=payload.top_k)
    return SearchResponseOut(
        results=[SearchResultOut.from_result(r) for r in response.results],
        cost_usd=response.cost_usd,
        is_confident=response.is_confident,
    )


@router.post("/export")
def export_search_results(payload: SearchRequest) -> StreamingResponse:
    response = search_service.search(payload.query, video_id=payload.video_id, top_k=payload.top_k)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["排名", "影片名稱", "時間範圍", "相似度", "融合分數", "命中來源", "片段描述"])
    for index, result in enumerate(response.results):
        writer.writerow([
            index + 1,
            result.video_title,
            _format_time_range(result.start_sec, result.end_sec),
            f"{round(result.similarity * 100)}%",
            f"{result.fusion_score:.3f}",
            result.hit_source,
            result.description,
        ])
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=search_results.csv"},
    )


def _format_time_range(start_sec: float, end_sec: float) -> str:
    def _mmss(sec: float) -> str:
        m, s = divmod(int(sec), 60)
        return f"{m:02d}:{s:02d}"

    return f"{_mmss(start_sec)}–{_mmss(end_sec)}"
