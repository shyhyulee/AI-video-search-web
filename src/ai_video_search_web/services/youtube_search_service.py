"""YouTube 搜尋 Application Service：用 yt-dlp 的 `ytsearch{n}:` 前綴查詢
YouTube，回傳影片 metadata 清單，供「YouTube 搜尋」頁使用。

刻意不引入 YouTube Data API v3：yt-dlp 已經是本專案的相依套件（downloader.py
在用），`ytsearch12:` 實測 1.6 秒就能拿到 12 筆含標題／網址／時長／頻道／
觀看數／縮圖／說明摘要的結果，不需要申請與保管 API 金鑰。代價是它靠解析
YouTube 網頁，官方改版時可能失效——這個風險下載功能本來就已經承擔。

分類上屬於 Category B（同步回應、不寫 DB、不進 jobs 表、不呼叫 OpenAI），
跟 search_service 同類，不經過 job_manager，見
docs/09-web-ui-migration-plan.md 2.1 節。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import yt_dlp

from .errors import YoutubeSearchError

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 12
MAX_LIMIT = 25

# 搜尋結果只需要 metadata，extract_flat 讓 yt-dlp 跳過逐支影片的完整解析
# （實測 12 筆 1.6 秒 vs 單支完整解析就要 3.6 秒）。js_runtimes／
# player_client 沿用 downloader.py 的設定，理由見該檔註解。
_SEARCH_OPTIONS = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,
    "skip_download": True,
    "js_runtimes": {"node": {}},
    "extractor_args": {"youtube": {"player_client": ["web_embedded"]}},
}

_CACHE_TTL_SEC = 300
_cache: dict[tuple[str, int], tuple[float, list["YoutubeSearchItem"]]] = {}
# API 的同步 endpoint 會被 FastAPI 丟到 threadpool 執行，同一時間可能有多個
# request 在讀寫 _cache，這裡用鎖保護。
_cache_lock = threading.Lock()


@dataclass
class YoutubeSearchItem:
    video_id: str
    title: str
    url: str
    description: str
    duration_sec: int | None
    channel: str
    view_count: int | None
    thumbnail_url: str | None


def search(query: str, limit: int = DEFAULT_LIMIT) -> list[YoutubeSearchItem]:
    """搜尋 YouTube 並回傳最多 limit 筆結果；查無結果回空 list（不是錯誤）。"""
    normalized = query.strip()
    if not normalized:
        return []
    limit = max(1, min(limit, MAX_LIMIT))

    cached = _cache_get(normalized, limit)
    if cached is not None:
        return cached

    try:
        with yt_dlp.YoutubeDL(_SEARCH_OPTIONS) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{normalized}", download=False)
    except Exception as exc:  # yt-dlp 例外種類很多，統一收斂成一種對外錯誤
        logger.error("YouTube 搜尋失敗：%s｜%s", normalized, exc, exc_info=True)
        raise YoutubeSearchError(f"YouTube 搜尋失敗：{exc}") from exc

    entries = (info or {}).get("entries") or []
    items = [_to_item(e) for e in entries if e]
    _cache_put(normalized, limit, items)
    return items


def _to_item(entry: dict) -> YoutubeSearchItem:
    video_id = entry.get("id") or ""
    duration = entry.get("duration")
    return YoutubeSearchItem(
        video_id=video_id,
        title=entry.get("title") or "（無標題）",
        # flat 結果的 url 欄位已經是完整的 watch 網址，但直播／異常情況可能
        # 缺欄位，用 id 兜底，避免卡片出現空連結。
        url=entry.get("url") or f"https://www.youtube.com/watch?v={video_id}",
        description=entry.get("description") or "",
        # 直播中的影片沒有時長，前端顯示為 --:--。
        duration_sec=int(duration) if duration else None,
        channel=entry.get("channel") or entry.get("uploader") or "",
        view_count=entry.get("view_count"),
        thumbnail_url=_pick_thumbnail(entry.get("thumbnails"), video_id),
    )


def _pick_thumbnail(thumbnails: list[dict] | None, video_id: str) -> str | None:
    """挑面積最大的縮圖；yt-dlp 沒給就退回 YouTube 的固定縮圖網址。"""
    candidates = [t for t in (thumbnails or []) if t.get("url")]
    if candidates:
        return max(candidates, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))["url"]
    if video_id:
        return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    return None


def _cache_get(query: str, limit: int) -> list[YoutubeSearchItem] | None:
    with _cache_lock:
        hit = _cache.get((query, limit))
        if hit is None:
            return None
        cached_at, items = hit
        if time.monotonic() - cached_at > _CACHE_TTL_SEC:
            del _cache[(query, limit)]
            return None
        return items


def _cache_put(query: str, limit: int, items: list[YoutubeSearchItem]) -> None:
    with _cache_lock:
        _cache[(query, limit)] = (time.monotonic(), items)
