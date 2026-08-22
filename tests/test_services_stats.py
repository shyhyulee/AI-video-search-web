"""stats_service 是薄包裝層，測試重點是正確委派給 db.get_header_stats()。"""
from __future__ import annotations

from ai_video_search_web.services import stats_service


def test_get_header_stats_delegates_to_db(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(stats_service.db, "get_header_stats", lambda: sentinel)
    assert stats_service.get_header_stats() is sentinel
