"""search API：monkeypatch search_service.search 避免真的呼叫 OpenAI，重點
測 request/response 轉換與 CSV 匯出格式。
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
    monkeypatch.setattr(search_service, "search", lambda query, video_id=None, top_k=20: _fake_response())

    resp = client.post("/api/v1/search", json={"query": "找機器人"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["cost_usd"] == 0.001
    assert body["is_confident"] is True
    assert len(body["results"]) == 1
    assert body["results"][0]["video_title"] == "測試影片"
    assert body["results"][0]["start_sec"] == 65.0


def test_search_export_returns_csv(client, monkeypatch):
    monkeypatch.setattr(search_service, "search", lambda query, video_id=None, top_k=20: _fake_response())

    resp = client.post("/api/v1/search/export", json={"query": "找機器人"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    body = resp.text
    assert "排名,影片名稱,時間範圍,相似度,融合分數,命中來源,片段描述" in body
    assert "測試影片" in body
    assert "01:05–01:30" in body
