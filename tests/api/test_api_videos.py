"""videos API：關鍵驗收條件——分析超長影片回 422、YouTube 重複網址回 409，
見 docs/09-web-ui-migration-plan.md 4.3 節。
"""
from __future__ import annotations

import io

from ai_video_search_web import db
from ai_video_search_web.pipeline import analyzer
from ai_video_search_web.services import job_manager

from conftest import make_video


def _add_segment(
    video_id: int,
    transcript: str | None = None,
    visual_description: str | None = None,
    ocr_text: str | None = None,
) -> int:
    return db.insert_segment(
        video_id=video_id, start_sec=0.0, end_sec=5.0,
        transcript=transcript, visual_description=visual_description, ocr_text=ocr_text,
        transcript_embedding=None, visual_embedding=None,
        asr_model=None, vlm_model=None, embedding_model=None,
    )


def test_list_videos_empty(client):
    resp = client.get("/api/v1/videos")
    assert resp.status_code == 200
    assert resp.json() == []


def test_analyzing_video_stays_in_pending_list_and_out_of_library(client):
    """驗收條件：分析中的影片在任何時刻都至少屬於一個清單。

    `?status=pending` ＝「影片與分析」頁，不帶 status ＝「影片庫」。analyzing
    落在前者；兩個端點都不收的話，影片會在整段分析期間從畫面上消失。
    """
    analyzing_id = make_video(status=db.STATUS_ANALYZING)

    pending_ids = [v["id"] for v in client.get("/api/v1/videos?status=pending").json()]
    library_ids = [v["id"] for v in client.get("/api/v1/videos").json()]

    assert analyzing_id in pending_ids
    assert analyzing_id not in library_ids


# ----------------------------------------------------------------------
# has_transcript／has_visual／has_ocr：從 segments 衍生的三個旗標。特徵測試，
# 鎖住「任一片段有內容就是 True、空字串不算內容、沒有片段就全 False」的語意。
# ----------------------------------------------------------------------
def test_video_modality_flags_are_true_when_any_segment_has_content(client):
    video_id = make_video(status=db.STATUS_ANALYZED)
    _add_segment(video_id, transcript="有字幕")
    _add_segment(video_id, visual_description="有畫面描述")
    _add_segment(video_id, ocr_text="有畫面文字")

    body = client.get(f"/api/v1/videos/{video_id}").json()

    assert (body["has_transcript"], body["has_visual"], body["has_ocr"]) == (True, True, True)


def test_video_modality_flags_are_false_without_matching_segment_content(client):
    video_id = make_video(status=db.STATUS_ANALYZED)
    _add_segment(video_id, transcript="只有字幕")

    body = client.get(f"/api/v1/videos/{video_id}").json()

    assert (body["has_transcript"], body["has_visual"], body["has_ocr"]) == (True, False, False)


def test_video_modality_flags_treat_empty_string_as_no_content(client):
    """`any(s.transcript for s in segments)` 的語意：空字串是 falsy，不算有內容。"""
    video_id = make_video(status=db.STATUS_ANALYZED)
    _add_segment(video_id, transcript="", visual_description="", ocr_text="")

    body = client.get(f"/api/v1/videos/{video_id}").json()

    assert (body["has_transcript"], body["has_visual"], body["has_ocr"]) == (False, False, False)


def test_video_modality_flags_are_false_when_video_has_no_segments(client):
    video_id = make_video(status=db.STATUS_ANALYZED)

    body = client.get(f"/api/v1/videos/{video_id}").json()

    assert (body["has_transcript"], body["has_visual"], body["has_ocr"]) == (False, False, False)


def test_list_videos_reports_flags_per_video_not_shared(client):
    """清單端點的旗標必須各算各的，不能因為改成一次查詢就串到別支影片身上。"""
    with_transcript = make_video(status=db.STATUS_ANALYZED)
    with_ocr = make_video(status=db.STATUS_ANALYZED)
    without_segments = make_video(status=db.STATUS_ANALYZED)
    _add_segment(with_transcript, transcript="有字幕")
    _add_segment(with_ocr, ocr_text="有畫面文字")

    body = client.get("/api/v1/videos").json()
    flags = {
        item["id"]: (item["has_transcript"], item["has_visual"], item["has_ocr"]) for item in body
    }

    assert flags[with_transcript] == (True, False, False)
    assert flags[with_ocr] == (False, False, True)
    assert flags[without_segments] == (False, False, False)


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


# ----------------------------------------------------------------------
# 重新分析：分析成功過的影片留在影片庫原地跑完，舊片段留到新結果寫入前才換掉；
# 從沒成功過的（第一次就失敗）才回到 pending。見 video_service.prepare_reanalysis()。
# ----------------------------------------------------------------------
def _stub_analysis_that_never_completes(monkeypatch):
    import threading

    def _start(video_id, q):
        thread = threading.Thread(target=lambda: None, daemon=True)
        thread.start()
        return thread

    monkeypatch.setattr(job_manager.analyzer, "start_analysis", _start)


def test_reanalyze_analyzed_video_stays_in_library_and_keeps_segments(client, monkeypatch):
    _stub_analysis_that_never_completes(monkeypatch)
    video_id = make_video()
    _add_segment(video_id, transcript="舊的分析結果")
    db.mark_video_analyzed(
        video_id=video_id, segment_count=1, cost_usd=0.05,
        asr_model="a", vlm_model="v", embedding_model="e",
    )

    assert client.post(f"/api/v1/videos/{video_id}/reanalyze").status_code == 202

    assert db.get_video(video_id).status == db.STATUS_ANALYZING
    # 舊片段還在，重新分析期間影片照樣搜得到——analyzer 要到寫入索引那一刻
    # 才換掉它們。
    assert len(db.list_segments_for_video(video_id)) == 1
    assert video_id in [v["id"] for v in client.get("/api/v1/videos").json()]
    assert video_id not in [v["id"] for v in client.get("/api/v1/videos?status=pending").json()]


def test_reanalyze_never_analyzed_video_goes_back_to_pending(client, monkeypatch):
    """第一次分析就失敗的影片沒有可保留的結果，回到 pending 才正確反映
    「這支還沒有東西」，也順便清掉部分寫入的殘骸。"""
    _stub_analysis_that_never_completes(monkeypatch)
    video_id = make_video()
    _add_segment(video_id, transcript="失敗前寫到一半的片段")
    db.update_video_status(video_id, db.STATUS_FAILED, "分析失敗：模擬錯誤")

    assert client.post(f"/api/v1/videos/{video_id}/reanalyze").status_code == 202

    assert db.list_segments_for_video(video_id) == []
    assert video_id in [v["id"] for v in client.get("/api/v1/videos?status=pending").json()]


def test_reanalyze_rejected_by_validation_leaves_status_untouched(client):
    """驗證失敗時不能留下「狀態被改掉、卻沒有工作在跑」的影片——那會讓它
    永遠停在分析中。這裡用重複觸發（409）當驗證失敗的代表。"""
    video_id = make_video()
    db.mark_video_analyzed(
        video_id=video_id, segment_count=1, cost_usd=0.05,
        asr_model="a", vlm_model="v", embedding_model="e",
    )
    db.insert_job(job_type=db.JOB_TYPE_ANALYSIS, video_id=video_id)  # 已有排隊中的工作

    resp = client.post(f"/api/v1/videos/{video_id}/reanalyze")

    assert resp.status_code == 409
    assert db.get_video(video_id).status == db.STATUS_ANALYZED


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
    # 逐欄位比對而不是只看 code：這個 body 原本是端點自己手刻的 JSONResponse，
    # 改走統一的例外對映之後形狀必須一模一樣，前端才不會受影響。
    assert resp.json() == {
        "error": {"code": "THUMBNAIL_UNAVAILABLE", "message": "無法產生縮圖", "details": None}
    }


# ----------------------------------------------------------------------
# 整理成文件（POST/GET /videos/{id}/document）
# ----------------------------------------------------------------------


def _fake_document():
    from ai_video_search_web.pipeline.document import DocumentSection, DocumentStep, VideoDocument

    return VideoDocument(
        doc_type="sop", title="生產流程", overview="概述",
        sections=[DocumentSection(heading="階段一", steps=[
            DocumentStep(timestamp_sec=12.0, heading="塗矽膏", detail="刷過鋼板"),
        ])],
        uncovered=[],
    )


def test_generate_document_returns_document_and_persists_type(client, monkeypatch):
    from ai_video_search_web.services import video_service

    video_id = make_video(status=db.STATUS_ANALYZED)
    _add_segment(video_id, transcript="第一步")
    monkeypatch.setattr(
        video_service.document_pipeline, "generate_document",
        lambda client_, title, segments: type("R", (), {"document": _fake_document(), "cost_usd": 0.005})(),
    )

    resp = client.post(f"/api/v1/videos/{video_id}/document")

    assert resp.status_code == 200
    body = resp.json()
    assert body["document"]["doc_type"] == "sop"
    assert body["document"]["sections"][0]["steps"][0]["timestamp_sec"] == 12.0
    # 清單只帶類型不帶內容
    listed = client.get("/api/v1/videos").json()[0]
    assert listed["document_type"] == "sop"
    assert "document_json" not in listed


def test_generate_document_also_refreshes_the_summary(client, monkeypatch):
    """「整理成文件」與「產生摘要」合併成一個動作：同一次呼叫的 overview 會寫回
    videos.summary。摘要不能只當顯示欄位——搜尋的影片層級篩選與影片庫的主題分類
    都在讀它。"""
    from ai_video_search_web.services import video_service

    video_id = make_video(status=db.STATUS_ANALYZED)
    _add_segment(video_id, transcript="第一步")
    db.update_video_summary(video_id, "分析時產生的舊摘要", "gpt-4o-mini", 0.0)
    monkeypatch.setattr(
        video_service.document_pipeline, "generate_document",
        lambda client_, title, segments: type("R", (), {"document": _fake_document(), "cost_usd": 0.005})(),
    )

    client.post(f"/api/v1/videos/{video_id}/document")

    listed = client.get("/api/v1/videos").json()[0]
    assert listed["summary"] == _fake_document().overview
    assert listed["summary"] != "分析時產生的舊摘要"


def test_generate_document_missing_video_returns_404_not_422(client):
    """/summary 對不存在的 video 會回 422（先查片段再查影片），這支刻意不照抄
    那個順序，維持 _get_video_or_raise 的 404 慣例。"""
    resp = client.post("/api/v1/videos/999/document")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "VIDEO_NOT_FOUND"


def test_generate_document_no_segments_returns_422(client):
    video_id = make_video(status=db.STATUS_ANALYZED)
    resp = client.post(f"/api/v1/videos/{video_id}/document")
    assert resp.status_code == 422


def test_get_document_before_generating_returns_404(client):
    """還沒整理過是正常狀態，前端靠這個 404 決定顯示「尚未整理」。"""
    video_id = make_video(status=db.STATUS_ANALYZED)
    resp = client.get(f"/api/v1/videos/{video_id}/document")
    assert resp.status_code == 404
    # 逐欄位比對，理由同 test_thumbnail_unavailable_for_nonexistent_file_returns_404。
    assert resp.json() == {
        "error": {
            "code": "DOCUMENT_NOT_FOUND",
            "message": "這支影片還沒有整理過的文件",
            "details": None,
        }
    }


def test_get_document_returns_stored_document(client):
    video_id = make_video(status=db.STATUS_ANALYZED)
    db.update_video_document(
        video_id, _fake_document().model_dump_json(), "sop", "gpt-4o-mini", "概述", 0.005
    )

    resp = client.get(f"/api/v1/videos/{video_id}/document")

    assert resp.status_code == 200
    assert resp.json()["document"]["title"] == "生產流程"
    assert resp.json()["model"] == "gpt-4o-mini"
