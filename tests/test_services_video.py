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


def test_register_uploaded_video_inserts_local_source_with_explicit_title(monkeypatch):
    captured = {}

    def fake_insert_video(**kwargs):
        captured.update(kwargs)
        return 7

    monkeypatch.setattr(video_service.db, "insert_video", fake_insert_video)

    video_id = video_service.register_uploaded_video(
        "使用者看到的標題", Path("/tmp/uploads/deadbeef.mp4"), duration_sec=99
    )

    assert video_id == 7
    assert captured["source"] == db.SOURCE_LOCAL
    # 標題來自呼叫端明確傳入，不是磁碟上的 uuid 檔名（跟舊版
    # register_local_video 用 path.stem 當標題的差別）。
    assert captured["title"] == "使用者看到的標題"
    assert captured["file_path"] == "/tmp/uploads/deadbeef.mp4"
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


def test_list_unanalyzed_videos_delegates_to_db(monkeypatch):
    sentinel = [object()]
    monkeypatch.setattr(video_service.db, "list_unanalyzed_videos", lambda: sentinel)
    assert video_service.list_unanalyzed_videos() is sentinel


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


def test_generate_document_generates_and_persists(monkeypatch):
    """service 層只驗證委派：有把整包 JSON、doc_type、model 名與成本正確
    傳給 db.update_video_document()。文件內容的邏輯在 test_document.py。"""
    fake_client = object()
    monkeypatch.setattr(video_service, "get_client", lambda: fake_client)

    fake_document = video_service.document_pipeline.VideoDocument(
        doc_type="sop", title="生產流程", overview="概述",
        sections=[], uncovered=[],
    )
    fake_result = MagicMock(document=fake_document, cost_usd=0.005)
    captured_generate = {}

    def fake_generate_document(client, video_title, segments):
        captured_generate.update(client=client, video_title=video_title, segments=segments)
        return fake_result

    monkeypatch.setattr(video_service.document_pipeline, "generate_document", fake_generate_document)

    captured_update = {}
    monkeypatch.setattr(
        video_service.db, "update_video_document",
        lambda video_id, document_json, document_type, document_model, additional_cost_usd: captured_update.update(
            video_id=video_id, document_json=document_json, document_type=document_type,
            document_model=document_model, additional_cost_usd=additional_cost_usd,
        ),
    )

    video = MagicMock(id=3, title="技嘉主板工廠")
    segments = [MagicMock()]
    result = video_service.generate_document(video, segments)

    assert result is fake_result
    assert captured_generate == {"client": fake_client, "video_title": "技嘉主板工廠", "segments": segments}
    assert captured_update["video_id"] == 3
    assert captured_update["document_type"] == "sop"
    assert captured_update["document_model"] == video_service.document_pipeline.MODEL_NAME
    assert captured_update["additional_cost_usd"] == 0.005
    # 存的是整包 JSON，形狀由 pipeline 的 pydantic 模型決定
    assert '"doc_type":"sop"' in captured_update["document_json"].replace(" ", "")


def test_load_document_returns_none_when_never_generated():
    assert video_service.load_document(MagicMock(document_json=None)) is None


def test_load_document_parses_stored_json():
    stored = video_service.document_pipeline.VideoDocument(
        doc_type="tutorial", title="壽司做法", overview="概述", sections=[], uncovered=[],
    ).model_dump_json()

    loaded = video_service.load_document(MagicMock(document_json=stored))

    assert loaded is not None
    assert loaded.doc_type == "tutorial"
    assert loaded.title == "壽司做法"
