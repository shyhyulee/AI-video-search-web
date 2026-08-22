"""videos API：關鍵驗收條件——分析超長影片回 422、YouTube 重複網址回 409，
見 docs/09-web-ui-migration-plan.md 4.3 節。
"""
from __future__ import annotations

import io

from ai_video_search_web import db
from ai_video_search_web.pipeline import analyzer

from conftest import make_video


def test_list_videos_empty(client):
    resp = client.get("/api/v1/videos")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_video_not_found_returns_404_with_error_schema(client):
    resp = client.get("/api/v1/videos/999")
    assert resp.status_code == 404
    assert resp.json() == {
        "error": {"code": "VIDEO_NOT_FOUND", "message": "找不到影片 999", "details": None}
    }


def test_delete_video_not_found_returns_404(client):
    resp = client.delete("/api/v1/videos/999")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "VIDEO_NOT_FOUND"


def test_delete_video_removes_record(client):
    video_id = make_video()
    resp = client.delete(f"/api/v1/videos/{video_id}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True}
    assert client.get(f"/api/v1/videos/{video_id}").status_code == 404


def test_analyze_video_not_found_returns_404(client):
    resp = client.post("/api/v1/videos/999/analyze")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "VIDEO_NOT_FOUND"


def test_analyze_video_over_duration_limit_returns_422(client):
    over_limit_sec = analyzer.MAX_DURATION_SEC + 1
    video_id = make_video(duration_sec=over_limit_sec)

    resp = client.post(f"/api/v1/videos/{video_id}/analyze")

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "DURATION_LIMIT_EXCEEDED"


def test_youtube_download_duplicate_url_returns_409(client, monkeypatch):
    from ai_video_search_web.services import video_service

    monkeypatch.setattr(video_service, "is_youtube_url", lambda url: True)
    db.insert_video(
        title="已存在", source=db.SOURCE_YOUTUBE, source_url="https://youtu.be/dup",
        file_path="/nonexistent.mp4", duration_sec=100,
    )

    resp = client.post("/api/v1/videos/youtube", json={"url": "https://youtu.be/dup"})

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "DUPLICATE_JOB"


def test_youtube_download_invalid_url_returns_400(client):
    resp = client.post("/api/v1/videos/youtube", json={"url": "not a youtube url"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_URL"


def test_upload_video_rejects_unsupported_extension(client):
    resp = client.post(
        "/api/v1/videos/upload",
        files={"file": ("note.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert resp.status_code == 422


def test_upload_video_accepts_mp4(client):
    resp = client.post(
        "/api/v1/videos/upload",
        files={"file": ("我的影片.mp4", io.BytesIO(b"fake mp4 bytes"), "video/mp4")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "我的影片"
    assert body["source"] == "local"
    assert body["status"] == "pending"
    # 讀不出真的長度（假造的位元組不是有效 mp4），probe_local_duration()
    # 讀不到就回傳 None、不擋住新增流程——duration_sec 應該是 None 而不是報錯。
    assert body["duration_sec"] is None


def test_regenerate_summary_no_segments_returns_422(client):
    video_id = make_video(status=db.STATUS_ANALYZED)
    resp = client.post(f"/api/v1/videos/{video_id}/summary")
    assert resp.status_code == 422


def test_stream_video_not_found_returns_404(client):
    resp = client.get("/api/v1/videos/999/stream")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "VIDEO_NOT_FOUND"


def test_thumbnail_video_not_found_returns_404(client):
    resp = client.get("/api/v1/videos/999/thumbnail")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "VIDEO_NOT_FOUND"


def test_thumbnail_unavailable_for_nonexistent_file_returns_404(client):
    video_id = make_video()  # file_path 指向不存在的檔案
    resp = client.get(f"/api/v1/videos/{video_id}/thumbnail")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "THUMBNAIL_UNAVAILABLE"
