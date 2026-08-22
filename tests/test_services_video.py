"""video_service 是薄包裝層，測試重點是「正確委派給底層 db／downloader／
analyzer／summary pipeline 函式」，不重複測試這些函式本身的邏輯（已經在
test_db.py／test_analyzer.py／test_summary.py 測過）。
"""
from __future__ import annotations

from unittest.mock import MagicMock
from pathlib import Path

from ai_video_search_web import db
from ai_video_search_web.services import video_service


def test_is_youtube_url_delegates_to_downloader(monkeypatch):
    monkeypatch.setattr(video_service.downloader, "is_youtube_url", lambda url: url == "yes")
    assert video_service.is_youtube_url("yes") is True
    assert video_service.is_youtube_url("no") is False


def test_find_existing_by_url_delegates_to_db(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(video_service.db, "find_by_source_url", lambda url: sentinel)
    assert video_service.find_existing_by_url("http://x") is sentinel


def test_register_downloaded_video_inserts_youtube_source(monkeypatch):
    captured = {}

    def fake_insert_video(**kwargs):
        captured.update(kwargs)
        return 42

    monkeypatch.setattr(video_service.db, "insert_video", fake_insert_video)

    video_id = video_service.register_downloaded_video(
        title="t", source_url="u", file_path=Path("/tmp/x.mp4"), duration_sec=10
    )

    assert video_id == 42
    assert captured["source"] == db.SOURCE_YOUTUBE
    assert captured["source_url"] == "u"
    assert captured["file_path"] == "/tmp/x.mp4"
    assert captured["duration_sec"] == 10


def test_register_local_video_inserts_local_source(monkeypatch):
    captured = {}

    def fake_insert_video(**kwargs):
        captured.update(kwargs)
        return 7

    monkeypatch.setattr(video_service.db, "insert_video", fake_insert_video)

    video_id = video_service.register_local_video(Path("/tmp/my video.mp4"), duration_sec=99)

    assert video_id == 7
    assert captured["source"] == db.SOURCE_LOCAL
    assert captured["title"] == "my video"
    assert captured["source_url"] is None


def test_probe_local_duration_returns_none_when_ffprobe_fails(tmp_path):
    # 不存在的檔案，ffprobe 一定會失敗（非 0 return code），驗證「讀不到就回傳
    # None、不擋流程」，不需要 mock subprocess。
    assert video_service.probe_local_duration(tmp_path / "missing.mp4") is None


def test_is_within_duration_limit_delegates_to_analyzer():
    assert video_service.is_within_duration_limit(10) is True
    assert video_service.is_within_duration_limit(10**9) is False


def test_max_duration_minutes_matches_analyzer_constant():
    assert video_service.max_duration_minutes() == video_service.analyzer.MAX_DURATION_SEC // 60


def test_list_pending_videos_delegates_to_db(monkeypatch):
    sentinel = [object()]
    monkeypatch.setattr(video_service.db, "list_pending_videos", lambda: sentinel)
    assert video_service.list_pending_videos() is sentinel


def test_list_library_videos_delegates_to_db(monkeypatch):
    sentinel = [object()]
    monkeypatch.setattr(video_service.db, "list_library_videos", lambda: sentinel)
    assert video_service.list_library_videos() is sentinel


def test_get_video_delegates_to_db(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(video_service.db, "get_video", lambda video_id: sentinel)
    assert video_service.get_video(1) is sentinel


def test_list_segments_for_video_delegates_to_db(monkeypatch):
    sentinel = [object()]
    monkeypatch.setattr(video_service.db, "list_segments_for_video", lambda video_id: sentinel)
    assert video_service.list_segments_for_video(1) is sentinel


def test_delete_video_unlinks_file_and_returns_no_error(monkeypatch, tmp_path):
    existing_file = tmp_path / "video.mp4"
    existing_file.write_bytes(b"x")
    record = MagicMock(file_path=str(existing_file), title="t")
    monkeypatch.setattr(video_service.db, "delete_video", lambda video_id: record)

    result, error = video_service.delete_video(1)

    assert result is record
    assert error is None
    assert not existing_file.exists()


def test_delete_video_returns_none_when_record_not_found(monkeypatch):
    monkeypatch.setattr(video_service.db, "delete_video", lambda video_id: None)
    result, error = video_service.delete_video(999)
    assert result is None
    assert error is None


def test_delete_video_missing_file_is_not_an_error(monkeypatch, tmp_path):
    # unlink(missing_ok=True)：檔案本來就不存在不算錯誤，維持既有行為。
    record = MagicMock(file_path=str(tmp_path / "already-gone.mp4"), title="t")
    monkeypatch.setattr(video_service.db, "delete_video", lambda video_id: record)

    result, error = video_service.delete_video(1)

    assert result is record
    assert error is None


def test_delete_video_returns_error_message_when_unlink_fails(monkeypatch, tmp_path):
    record = MagicMock(file_path=str(tmp_path / "video.mp4"), title="t")
    monkeypatch.setattr(video_service.db, "delete_video", lambda video_id: record)

    def _raise_oserror(self, missing_ok=True):
        raise OSError("boom")

    monkeypatch.setattr(video_service.Path, "unlink", _raise_oserror)

    result, error = video_service.delete_video(1)

    assert result is record
    assert error == "boom"


def test_reset_to_pending_delegates_to_db(monkeypatch):
    called = {}
    monkeypatch.setattr(
        video_service.db, "reset_to_pending", lambda video_id: called.setdefault("id", video_id)
    )
    video_service.reset_to_pending(5)
    assert called["id"] == 5


def test_regenerate_summary_generates_and_persists(monkeypatch):
    fake_client = object()
    monkeypatch.setattr(video_service, "get_client", lambda: fake_client)

    fake_result = MagicMock(summary="摘要內容", cost_usd=0.01)
    captured_generate_args = {}

    def fake_generate_summary(client, segments):
        captured_generate_args["client"] = client
        captured_generate_args["segments"] = segments
        return fake_result

    monkeypatch.setattr(video_service.summary_pipeline, "generate_summary", fake_generate_summary)

    captured_update_args = {}

    def fake_update_video_summary(video_id, summary, summary_model, additional_cost_usd):
        captured_update_args.update(
            video_id=video_id, summary=summary, summary_model=summary_model,
            additional_cost_usd=additional_cost_usd,
        )

    monkeypatch.setattr(video_service.db, "update_video_summary", fake_update_video_summary)

    segments = [MagicMock()]
    result = video_service.regenerate_summary(3, segments)

    assert result is fake_result
    assert captured_generate_args == {"client": fake_client, "segments": segments}
    assert captured_update_args == {
        "video_id": 3,
        "summary": "摘要內容",
        "summary_model": video_service.summary_pipeline.MODEL_NAME,
        "additional_cost_usd": 0.01,
    }
