"""search_service 是薄包裝層，測試重點是正確委派給 pipeline.search.search()。"""
from __future__ import annotations

from ai_video_search_web.services import search_service


def test_search_delegates_to_pipeline(monkeypatch):
    captured = {}

    def fake_search(query, top_k=20, video_id=None):
        captured.update(query=query, top_k=top_k, video_id=video_id)
        return "sentinel-response"

    monkeypatch.setattr(search_service.search_pipeline, "search", fake_search)

    result = search_service.search("找機器人", video_id=3, top_k=5)

    assert result == "sentinel-response"
    assert captured == {"query": "找機器人", "top_k": 5, "video_id": 3}


def test_search_defaults_top_k_and_video_id(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        search_service.search_pipeline,
        "search",
        lambda query, top_k=20, video_id=None: captured.update(top_k=top_k, video_id=video_id),
    )

    search_service.search("找機器人")

    assert captured == {"top_k": 20, "video_id": None}
