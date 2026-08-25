"""YouTube 搜尋 API：查詢 YouTube 影片 metadata，供「YouTube 搜尋」頁的
卡片列表使用。

跟 /videos/youtube（下載）不同，這裡完全不落地：不下載檔案、不寫 videos 表、
不建 job，只是把 yt-dlp 的搜尋結果轉成 JSON 回前端。
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..schemas.youtube import YoutubeSearchItemOut, YoutubeSearchResponseOut
from ..services import youtube_search_service

router = APIRouter(prefix="/youtube", tags=["youtube"])


@router.get("/search", response_model=YoutubeSearchResponseOut)
def search_youtube(
    q: str = Query(min_length=1, description="搜尋關鍵字"),
    limit: int = Query(
        default=youtube_search_service.DEFAULT_LIMIT, ge=1, le=youtube_search_service.MAX_LIMIT
    ),
) -> YoutubeSearchResponseOut:
    items = youtube_search_service.search(q, limit=limit)
    return YoutubeSearchResponseOut(items=[YoutubeSearchItemOut.from_item(i) for i in items])
