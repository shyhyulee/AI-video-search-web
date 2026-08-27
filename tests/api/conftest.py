"""tests/api/ 共用 fixture：每個測試用獨立的臨時 DB 與臨時 video 目錄，並
重置 job_manager 的 process 級序列化狀態，避免測試之間互相污染，也避免
真的寫檔到專案的 app.db／video/ 目錄。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ai_video_search_web import db, downloader
from ai_video_search_web.services import job_manager


@pytest.fixture
def temp_db(clean_db, tmp_path, monkeypatch):
    """覆寫 tests/conftest.py 的同名 fixture，補上這個目錄需要的額外隔離。

    資料庫本身的清空交給 `clean_db`（見 tests/conftest.py）；這裡只多做
    影片目錄與 job_manager 全域狀態的隔離。
    """
    monkeypatch.setattr(downloader, "VIDEO_DIR", tmp_path / "video")
    monkeypatch.setattr(job_manager, "_analysis_running", False)


@pytest.fixture
def client(temp_db):
    from ai_video_search_web.api.main import app

    with TestClient(app) as test_client:
        yield test_client


def make_video(duration_sec: int = 100, status: str = db.STATUS_PENDING) -> int:
    """建立一筆測試用影片紀錄；file_path 指向不存在的路徑，測試不需要真的
    讀取影片檔內容（分析／串流／縮圖等真的碰檔案的行為在別的測試已覆蓋，
    這裡只測 API／Job Manager 的邏輯層）。
    """
    video_id = db.insert_video(
        title="測試影片", source=db.SOURCE_LOCAL, source_url=None,
        file_path="/nonexistent.mp4", duration_sec=duration_sec,
    )
    if status != db.STATUS_PENDING:
        db.update_video_status(video_id, status)
    return video_id
