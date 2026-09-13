"""search API：monkeypatch search_service.search 避免真的呼叫 OpenAI，重點
測 request/response 轉換。
"""
from __future__ import annotations

from ai_video_search_web.pipeline.search import SearchResponse, SearchResult
from ai_video_search_web.services import search_service


def _fake_response() -> SearchResponse:
    result = SearchResult(
        segment_id=1, video_id=2, video_title="測試影片", start_sec=65.0, end_sec=90.0,
        similarity=0.87, hit_source="字幕＋畫面", description="有人在講話",
        transcript="逐字稿內容", transcript_score=0.9, visual_score=0.8, ocr_score=None,
        fusion_strategy="RRF", fusion_score=0.5,
    )
    return SearchResponse(results=[result], cost_usd=0.001, is_confident=True)


def test_search_returns_results(client, monkeypatch):
    monkeypatch.setattr(search_service, "search", lambda query, video_ids=None, top_k=20: _fake_response())

    resp = client.post("/api/v1/search", json={"query": "找機器人"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["cost_usd"] == 0.001
    assert body["is_confident"] is True
    assert len(body["results"]) == 1
    assert body["results"][0]["video_title"] == "測試影片"
    assert body["results"][0]["start_sec"] == 65.0


def test_search_passes_video_ids_scope_through(client, monkeypatch):
    """多選範圍要原封不動傳到 service 層（不是只取第一個、也不是丟掉）。"""
    captured = {}

    def fake_search(query, video_ids=None, top_k=20):
        captured.update(video_ids=video_ids, top_k=top_k)
        return _fake_response()

    monkeypatch.setattr(search_service, "search", fake_search)

    resp = client.post("/api/v1/search", json={"query": "找機器人", "video_ids": [4, 8, 15]})

    assert resp.status_code == 200
    assert captured == {"video_ids": [4, 8, 15], "top_k": 20}


def test_search_without_video_ids_means_no_scope(client, monkeypatch):
    """沒帶欄位＝搜全部，必須是 None 而不是空 list——空 list 在 pipeline 是
    「限定了範圍但一支都沒選」，會搜出零筆。"""
    captured = {}
    monkeypatch.setattr(
        search_service,
        "search",
        lambda query, video_ids=None, top_k=20: captured.update(video_ids=video_ids) or _fake_response(),
    )

    resp = client.post("/api/v1/search", json={"query": "找機器人"})

    assert resp.status_code == 200
    assert captured == {"video_ids": None}
