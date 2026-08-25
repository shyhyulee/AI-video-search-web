"""youtube API：monkeypatch 掉 yt_dlp.YoutubeDL 避免測試打真實網路，但保留
service 的欄位轉換（縮圖挑選、缺欄位兜底）與快取邏輯不被 mock 掉。

關鍵驗收條件：正常回 12 筆、空關鍵字回 422、yt-dlp 失敗回 502 且符合統一
Error Schema。
"""
from __future__ import annotations

import pytest
import yt_dlp

from ai_video_search_web.services import youtube_search_service


@pytest.fixture(autouse=True)
def clear_search_cache():
    """service 的快取是 module 級的，會跨測試殘留，每個測試前後都清乾淨。"""
    youtube_search_service._cache.clear()
    yield
    youtube_search_service._cache.clear()


def make_entry(index: int) -> dict:
    video_id = f"vid{index:03d}"
    return {
        "id": video_id,
        "title": f"測試影片 {index}",
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "description": "這是說明摘要...",
        "duration": 630,
        "channel": "測試頻道",
        "uploader": "測試上傳者",
        "view_count": 12345,
        "thumbnails": [
            {"url": "https://i.ytimg.com/small.jpg", "width": 360, "height": 202},
            {"url": "https://i.ytimg.com/large.jpg", "width": 720, "height": 404},
        ],
    }


class FakeYoutubeDL:
    """取代 yt_dlp.YoutubeDL 的 context manager；記錄呼叫次數供快取測試斷言。"""

    calls: list[str] = []
    entries: list[dict] = []
    error: Exception | None = None

    def __init__(self, _options):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return False

    def extract_info(self, url, download=False):
        FakeYoutubeDL.calls.append(url)
        if FakeYoutubeDL.error is not None:
            raise FakeYoutubeDL.error
        return {"entries": FakeYoutubeDL.entries}


@pytest.fixture
def fake_ydl(monkeypatch):
    FakeYoutubeDL.calls = []
    FakeYoutubeDL.entries = [make_entry(i) for i in range(1, 13)]
    FakeYoutubeDL.error = None
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    return FakeYoutubeDL


def test_search_returns_twelve_items(client, fake_ydl):
    resp = client.get("/api/v1/youtube/search", params={"q": "python 教學"})

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 12
    assert fake_ydl.calls == ["ytsearch12:python 教學"]
    assert items[0] == {
        "video_id": "vid001",
        "title": "測試影片 1",
        "url": "https://www.youtube.com/watch?v=vid001",
        "description": "這是說明摘要...",
        "duration_sec": 630,
        "channel": "測試頻道",
        "view_count": 12345,
        # 面積最大的那張，不是清單第一張
        "thumbnail_url": "https://i.ytimg.com/large.jpg",
    }


def test_search_missing_fields_fall_back(client, fake_ydl):
    fake_ydl.entries = [{"id": "abc123"}]

    resp = client.get("/api/v1/youtube/search", params={"q": "直播"})

    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["url"] == "https://www.youtube.com/watch?v=abc123"
    assert item["thumbnail_url"] == "https://i.ytimg.com/vi/abc123/hqdefault.jpg"
    assert item["duration_sec"] is None  # 直播中沒有時長
    assert item["channel"] == ""
    assert item["view_count"] is None
    assert item["title"] == "（無標題）"


def test_search_falls_back_to_uploader_when_channel_missing(client, fake_ydl):
    fake_ydl.entries = [{"id": "abc123", "uploader": "某上傳者"}]

    resp = client.get("/api/v1/youtube/search", params={"q": "測試"})

    assert resp.json()["items"][0]["channel"] == "某上傳者"


def test_search_empty_query_returns_422(client, fake_ydl):
    resp = client.get("/api/v1/youtube/search", params={"q": ""})

    assert resp.status_code == 422
    assert fake_ydl.calls == []


def test_search_query_is_required(client, fake_ydl):
    assert client.get("/api/v1/youtube/search").status_code == 422


def test_search_limit_out_of_range_returns_422(client, fake_ydl):
    assert client.get("/api/v1/youtube/search", params={"q": "x", "limit": 99}).status_code == 422
    assert client.get("/api/v1/youtube/search", params={"q": "x", "limit": 0}).status_code == 422


def test_search_respects_limit(client, fake_ydl):
    fake_ydl.entries = [make_entry(i) for i in range(1, 4)]

    resp = client.get("/api/v1/youtube/search", params={"q": "貓", "limit": 3})

    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 3
    assert fake_ydl.calls == ["ytsearch3:貓"]


def test_search_no_results_returns_empty_list(client, fake_ydl):
    fake_ydl.entries = []

    resp = client.get("/api/v1/youtube/search", params={"q": "不存在的關鍵字"})

    assert resp.status_code == 200
    assert resp.json() == {"items": []}


def test_search_caches_repeated_query(client, fake_ydl):
    client.get("/api/v1/youtube/search", params={"q": "重複查詢"})
    client.get("/api/v1/youtube/search", params={"q": "重複查詢"})

    assert len(fake_ydl.calls) == 1


def test_search_cache_key_includes_limit(client, fake_ydl):
    client.get("/api/v1/youtube/search", params={"q": "同關鍵字", "limit": 3})
    client.get("/api/v1/youtube/search", params={"q": "同關鍵字", "limit": 5})

    assert fake_ydl.calls == ["ytsearch3:同關鍵字", "ytsearch5:同關鍵字"]


def test_search_yt_dlp_failure_returns_502_with_error_schema(client, fake_ydl):
    fake_ydl.error = RuntimeError("Unable to extract yt initial data")

    resp = client.get("/api/v1/youtube/search", params={"q": "python"})

    assert resp.status_code == 502
    body = resp.json()
    assert body["error"]["code"] == "YOUTUBE_SEARCH_FAILED"
    assert "Unable to extract yt initial data" in body["error"]["message"]
    assert body["error"]["details"] is None


def test_search_failure_is_not_cached(client, fake_ydl):
    fake_ydl.error = RuntimeError("暫時性失敗")
    assert client.get("/api/v1/youtube/search", params={"q": "重試"}).status_code == 502

    fake_ydl.error = None
    resp = client.get("/api/v1/youtube/search", params={"q": "重試"})

    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 12
