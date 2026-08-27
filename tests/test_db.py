"""db.py 的特徵測試（characterization tests）：鎖住現有的 schema、migration、
COALESCE 寫入語意、級聯刪除、CRUD 行為，做為之後拆分 db.py 的安全網。

每個測試都用 monkeypatch 把 db.DB_PATH 導向 pytest 的 tmp_path（每個測試
獨立的臨時目錄），測試結束後 monkeypatch 自動還原，不會動到使用者的
app.db，也不會互相汙染。
"""
from __future__ import annotations

import pytest

from ai_video_search_web import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """初始化一個獨立的臨時 DB，每個測試都是全新檔案。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()


def _make_video(title: str = "測試影片", duration_sec: int = 100) -> int:
    return db.insert_video(
        title=title, source=db.SOURCE_LOCAL, source_url=None,
        file_path="/nonexistent.mp4", duration_sec=duration_sec,
    )


# ----------------------------------------------------------------------
# init_db() / migration
# ----------------------------------------------------------------------


def test_init_db_creates_all_tables(temp_db):
    with db.get_connection() as conn:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"videos", "segments", "ocr_events", "search_log"} <= tables


def test_init_db_is_idempotent(temp_db):
    # 重複呼叫不該出錯（CREATE TABLE IF NOT EXISTS + migration 欄位已存在就跳過）
    db.init_db()
    db.init_db()


def test_init_db_adds_migrated_columns(temp_db):
    # asr_model 等欄位不在 CREATE TABLE 的原始 schema 裡，完全靠 migration 補上
    with db.get_connection() as conn:
        video_columns = {row["name"] for row in conn.execute("PRAGMA table_info(videos)")}
        segment_columns = {row["name"] for row in conn.execute("PRAGMA table_info(segments)")}
    assert {"asr_model", "vlm_model", "embedding_model", "summary", "summary_model"} <= video_columns
    assert {"no_speech_prob", "avg_logprob", "compression_ratio", "ocr_embedding", "vlm_frame_count"} <= segment_columns


# ----------------------------------------------------------------------
# 基本 CRUD round-trip
# ----------------------------------------------------------------------


def test_insert_and_get_video_round_trip(temp_db):
    video_id = _make_video(title="my video", duration_sec=42)
    video = db.get_video(video_id)
    assert video.title == "my video"
    assert video.duration_sec == 42
    assert video.status == db.STATUS_PENDING


def test_get_video_missing_id_returns_none(temp_db):
    assert db.get_video(99999) is None


def test_find_by_source_url(temp_db):
    db.insert_video(
        title="t", source=db.SOURCE_YOUTUBE, source_url="https://youtu.be/x",
        file_path="/x.mp4", duration_sec=1,
    )
    found = db.find_by_source_url("https://youtu.be/x")
    assert found is not None
    assert found.title == "t"
    assert db.find_by_source_url("https://youtu.be/not-exist") is None


def test_insert_and_list_segments_round_trip(temp_db):
    video_id = _make_video()
    db.insert_segment(
        video_id=video_id, start_sec=0.0, end_sec=5.0,
        transcript="hello", visual_description="desc", ocr_text=None,
        transcript_embedding=None, visual_embedding=None,
        asr_model="whisper-1", vlm_model="gpt-4o-mini", embedding_model="text-embedding-3-small",
    )
    segments = db.list_segments_for_video(video_id)
    assert len(segments) == 1
    assert segments[0].transcript == "hello"
    assert segments[0].visual_description == "desc"
    assert segments[0].vlm_frame_count is None  # 沒傳就是 None，向後相容舊資料


def test_insert_segment_records_vlm_frame_count(temp_db):
    video_id = _make_video()
    db.insert_segment(
        video_id=video_id, start_sec=0.0, end_sec=10.0,
        transcript=None, visual_description="desc", ocr_text=None,
        transcript_embedding=None, visual_embedding=None,
        asr_model="whisper-1", vlm_model="gpt-4o-mini", embedding_model="text-embedding-3-small",
        vlm_frame_count=2,
    )
    segments = db.list_segments_for_video(video_id)
    assert segments[0].vlm_frame_count == 2


def test_insert_and_list_ocr_events_round_trip(temp_db):
    video_id = _make_video()
    db.insert_ocr_event(
        video_id=video_id, segment_id=None, start_sec=1.0, end_sec=3.0, frame_sec=2.0,
        raw_text="ABC-1234", resolved_text="ABC-1234", confidence=0.9, bbox=None,
        primary_engine="easyocr", ocr_pipeline_version="local-ocr-v1", embedding=None,
    )
    events = db.list_ocr_events_for_video(video_id)
    assert len(events) == 1
    assert events[0].resolved_text == "ABC-1234"


def test_insert_search_log(temp_db):
    db.insert_search_log("測試查詢", 0.00123)
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM search_log").fetchone()
    assert row["query"] == "測試查詢"
    assert row["cost_usd"] == pytest.approx(0.00123)


# ----------------------------------------------------------------------
# mark_video_analyzed() 的 COALESCE 語意
# ----------------------------------------------------------------------


def test_mark_video_analyzed_sets_summary_when_provided(temp_db):
    video_id = _make_video()
    db.mark_video_analyzed(
        video_id=video_id, segment_count=1, cost_usd=0.01,
        asr_model="a", vlm_model="v", embedding_model="e",
        summary="摘要內容", summary_model="gpt-4o-mini",
    )
    video = db.get_video(video_id)
    assert video.status == db.STATUS_ANALYZED
    assert video.summary == "摘要內容"
    assert video.summary_model == "gpt-4o-mini"


def test_mark_video_analyzed_preserves_summary_when_not_provided(temp_db):
    video_id = _make_video()
    db.mark_video_analyzed(
        video_id=video_id, segment_count=1, cost_usd=0.01,
        asr_model="a", vlm_model="v", embedding_model="e",
        summary="原本的摘要", summary_model="model-1",
    )
    # 第二次（模擬重新分析但這次自動摘要失敗）不傳 summary，應該保留原值
    db.mark_video_analyzed(
        video_id=video_id, segment_count=2, cost_usd=0.02,
        asr_model="a", vlm_model="v", embedding_model="e",
    )
    video = db.get_video(video_id)
    assert video.summary == "原本的摘要"
    assert video.summary_model == "model-1"
    assert video.segment_count == 2  # 其他欄位仍正常更新
    assert video.cost_usd == pytest.approx(0.02)


def test_update_video_summary_accumulates_cost(temp_db):
    video_id = _make_video()
    db.mark_video_analyzed(
        video_id=video_id, segment_count=1, cost_usd=0.10,
        asr_model="a", vlm_model="v", embedding_model="e",
    )
    db.update_video_summary(video_id, "摘要", "gpt-4o-mini", 0.02)
    video = db.get_video(video_id)
    assert video.summary == "摘要"
    assert video.cost_usd == pytest.approx(0.12)


# ----------------------------------------------------------------------
# reset_to_pending() / delete_video() 級聯刪除
# ----------------------------------------------------------------------


def test_reset_to_pending_clears_segments_and_ocr_events(temp_db):
    video_id = _make_video()
    db.insert_segment(
        video_id=video_id, start_sec=0.0, end_sec=1.0,
        transcript=None, visual_description=None, ocr_text=None,
        transcript_embedding=None, visual_embedding=None,
        asr_model=None, vlm_model=None, embedding_model=None,
    )
    db.insert_ocr_event(
        video_id=video_id, segment_id=None, start_sec=0.0, end_sec=1.0, frame_sec=0.5,
        raw_text="x", resolved_text="x", confidence=None, bbox=None,
        primary_engine="easyocr", ocr_pipeline_version="local-ocr-v1", embedding=None,
    )
    db.mark_video_analyzed(
        video_id=video_id, segment_count=1, cost_usd=0.05,
        asr_model="a", vlm_model="v", embedding_model="e", summary="摘要", summary_model="m",
    )

    db.reset_to_pending(video_id)

    assert db.list_segments_for_video(video_id) == []
    assert db.list_ocr_events_for_video(video_id) == []
    video = db.get_video(video_id)
    assert video.status == db.STATUS_PENDING
    assert video.summary is None
    assert video.cost_usd is None


def test_delete_video_cascades_and_returns_deleted_record(temp_db):
    video_id = _make_video(title="要刪除的影片")
    db.insert_segment(
        video_id=video_id, start_sec=0.0, end_sec=1.0,
        transcript=None, visual_description=None, ocr_text=None,
        transcript_embedding=None, visual_embedding=None,
        asr_model=None, vlm_model=None, embedding_model=None,
    )
    db.insert_ocr_event(
        video_id=video_id, segment_id=None, start_sec=0.0, end_sec=1.0, frame_sec=0.5,
        raw_text="x", resolved_text="x", confidence=None, bbox=None,
        primary_engine="easyocr", ocr_pipeline_version="local-ocr-v1", embedding=None,
    )

    deleted = db.delete_video(video_id)

    assert deleted is not None
    assert deleted.id == video_id
    assert deleted.title == "要刪除的影片"
    assert db.get_video(video_id) is None
    assert db.list_segments_for_video(video_id) == []
    assert db.list_ocr_events_for_video(video_id) == []


def test_delete_video_missing_id_returns_none(temp_db):
    assert db.delete_video(99999) is None


# ----------------------------------------------------------------------
# segments_fts 同步：FTS 表沒有用 external content，rowid 靠呼叫端自己維護，
# 每一條刪除片段的路徑都必須把對應的 FTS 列一起清掉。殘留列會佔掉
# fts_bm25_search() 的前 200 名額，把真正命中的片段擠出候選集。
# ----------------------------------------------------------------------
def _count_orphan_fts() -> int:
    with db.get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM segments_fts WHERE rowid NOT IN (SELECT id FROM segments)"
        ).fetchone()["c"]


def _insert_searchable_segment(video_id: int, transcript: str) -> int:
    return db.insert_segment(
        video_id=video_id, start_sec=0.0, end_sec=1.0,
        transcript=transcript, visual_description=None, ocr_text=None,
        transcript_embedding=None, visual_embedding=None,
        asr_model=None, vlm_model=None, embedding_model=None,
    )


@pytest.mark.parametrize(
    "delete_path",
    [db.reset_to_pending, db.delete_video, db.clear_analysis_output],
    ids=["reset_to_pending", "delete_video", "clear_analysis_output"],
)
def test_deleting_segments_also_clears_fts_rows(temp_db, delete_path):
    video_id = _make_video()
    _insert_searchable_segment(video_id, "獨特關鍵字內容")
    assert db.fts_bm25_search(["獨特關鍵字內容"]) != []

    delete_path(video_id)

    assert db.fts_bm25_search(["獨特關鍵字內容"]) == []
    assert _count_orphan_fts() == 0


def test_clear_analysis_output_keeps_video_columns(temp_db):
    """跟 reset_to_pending() 的差別：只清片段，videos 表一個欄位都不動——
    重新分析時 analyzer 靠它換掉舊索引，影片本身的狀態不歸它管。"""
    video_id = _make_video()
    _insert_searchable_segment(video_id, "舊的內容")
    db.mark_video_analyzed(
        video_id=video_id, segment_count=1, cost_usd=0.05,
        asr_model="a", vlm_model="v", embedding_model="e", summary="摘要", summary_model="m",
    )

    db.clear_analysis_output(video_id)

    assert db.list_segments_for_video(video_id) == []
    video = db.get_video(video_id)
    assert video.status == db.STATUS_ANALYZED
    assert video.summary == "摘要"
    assert video.analyzed_at is not None


def test_prune_orphan_fts_removes_rows_without_segment(temp_db):
    """修既有資料庫：delete_for_video() 出現之前留下的殘留列由 init_db() 清掉。"""
    video_id = _make_video()
    segment_id = _insert_searchable_segment(video_id, "會被偷偷刪掉的片段")
    # 模擬舊版行為：只刪 segments，不管 segments_fts。
    with db.get_connection() as conn:
        conn.execute("DELETE FROM segments WHERE id = ?", (segment_id,))
    assert _count_orphan_fts() == 1

    with db.get_connection() as conn:
        assert db.segments.prune_orphan_fts(conn) == 1

    assert _count_orphan_fts() == 0


# ----------------------------------------------------------------------
# 影片列表查詢（狀態篩選）
# ----------------------------------------------------------------------


def test_list_library_videos_includes_analyzed_and_failed_excludes_pending(temp_db):
    pending_id = _make_video(title="pending")
    analyzed_id = _make_video(title="analyzed")
    db.mark_video_analyzed(
        video_id=analyzed_id, segment_count=1, cost_usd=0.01,
        asr_model="a", vlm_model="v", embedding_model="e",
    )
    failed_id = _make_video(title="failed")
    db.update_video_status(failed_id, db.STATUS_FAILED, "分析失敗：模擬錯誤")
    analyzing_id = _make_video(title="analyzing")
    db.update_video_status(analyzing_id, db.STATUS_ANALYZING, "場景切分中")

    library_ids = {v.id for v in db.list_library_videos()}
    assert library_ids == {analyzed_id, failed_id}
    assert pending_id not in library_ids
    # 分析中的影片還沒有結果可看，不進影片庫——它待在
    # list_unanalyzed_videos()，兩個清單合起來必須涵蓋全部四種狀態。
    assert analyzing_id not in library_ids


def test_list_unanalyzed_videos_returns_pending_and_analyzing(temp_db):
    """分析中的影片必須留在「影片與分析」的清單裡。漏掉 analyzing 的話，影片
    會在整段分析期間從待分析清單與影片庫同時消失。"""
    pending_id = _make_video(title="pending")
    analyzing_id = _make_video(title="analyzing")
    db.update_video_status(analyzing_id, db.STATUS_ANALYZING, "場景切分中")
    analyzed_id = _make_video(title="analyzed")
    db.mark_video_analyzed(
        video_id=analyzed_id, segment_count=1, cost_usd=0.01,
        asr_model="a", vlm_model="v", embedding_model="e",
    )
    failed_id = _make_video(title="failed")
    db.update_video_status(failed_id, db.STATUS_FAILED, "分析失敗：模擬錯誤")

    unanalyzed_ids = {v.id for v in db.list_unanalyzed_videos()}
    assert unanalyzed_ids == {pending_id, analyzing_id}


def test_get_header_stats(temp_db):
    _make_video(title="pending")
    analyzed_id = _make_video(title="analyzed")
    db.mark_video_analyzed(
        video_id=analyzed_id, segment_count=5, cost_usd=0.10,
        asr_model="a", vlm_model="v", embedding_model="e",
    )

    stats = db.get_header_stats()
    assert stats.pending_count == 1
    assert stats.analyzed_count == 1
    assert stats.segment_count == 5
    assert stats.total_cost_usd == pytest.approx(0.10)


def test_get_header_stats_counts_analyzing_as_pending(temp_db):
    """分析中的影片算進 pending_count。只算 pending 的話，Header 的總數會在
    分析的那一分鐘裡短少一支（既不在「待分析」也還沒進「已分析」）。"""
    pending_id = _make_video(title="pending")
    analyzing_id = _make_video(title="analyzing")
    db.update_video_status(analyzing_id, db.STATUS_ANALYZING, "場景切分中")

    stats = db.get_header_stats()
    assert stats.pending_count == 2
    assert stats.analyzed_count == 0

    # 分析完成後它離開 pending_count、進入 analyzed_count，總數全程不變。
    db.mark_video_analyzed(
        video_id=analyzing_id, segment_count=3, cost_usd=0.05,
        asr_model="a", vlm_model="v", embedding_model="e",
    )
    stats = db.get_header_stats()
    assert stats.pending_count == 1
    assert stats.analyzed_count == 1
    assert pending_id in {v.id for v in db.list_unanalyzed_videos()}


# ----------------------------------------------------------------------
# modality_flags_by_video()：VideoOut 三個模態旗標的聚合查詢
# ----------------------------------------------------------------------


def _insert_segment_with_modalities(
    video_id: int,
    transcript: str | None = None,
    visual_description: str | None = None,
    ocr_text: str | None = None,
) -> int:
    return db.insert_segment(
        video_id=video_id, start_sec=0.0, end_sec=5.0,
        transcript=transcript, visual_description=visual_description, ocr_text=ocr_text,
        transcript_embedding=None, visual_embedding=None,
        asr_model="a", vlm_model="v", embedding_model="e",
    )


def test_modality_flags_aggregates_across_segments_of_the_same_video(temp_db):
    video_id = _make_video()
    _insert_segment_with_modalities(video_id, transcript="有字幕")
    _insert_segment_with_modalities(video_id, ocr_text="有畫面文字")

    flags = db.modality_flags_by_video()

    assert flags[video_id] == db.ModalityFlags(has_transcript=True, has_visual=False, has_ocr=True)


def test_modality_flags_treats_null_and_empty_string_as_no_content(temp_db):
    """對應 VideoOut 原本的 `any(s.transcript for s in segments)`：空字串是 falsy。"""
    video_id = _make_video()
    _insert_segment_with_modalities(video_id, transcript="", visual_description=None, ocr_text="  ")

    flags = db.modality_flags_by_video()

    # 空字串與 NULL 都算沒內容；空白字元字串在 Python truthiness 下是有內容
    assert flags[video_id] == db.ModalityFlags(has_transcript=False, has_visual=False, has_ocr=True)


def test_modality_flags_keeps_videos_separate(temp_db):
    first = _make_video(title="A")
    second = _make_video(title="B")
    _insert_segment_with_modalities(first, transcript="只有 A 有字幕")
    _insert_segment_with_modalities(second, visual_description="只有 B 有畫面描述")

    flags = db.modality_flags_by_video()

    assert flags[first] == db.ModalityFlags(has_transcript=True)
    assert flags[second] == db.ModalityFlags(has_visual=True)


def test_modality_flags_omits_videos_without_segments(temp_db):
    video_id = _make_video()

    assert db.modality_flags_by_video() == {}
    assert db.modality_flags_by_video([video_id]) == {}


def test_modality_flags_filters_by_video_ids(temp_db):
    wanted = _make_video(title="要查的")
    other = _make_video(title="不查的")
    _insert_segment_with_modalities(wanted, transcript="甲")
    _insert_segment_with_modalities(other, transcript="乙")

    flags = db.modality_flags_by_video([wanted])

    assert set(flags) == {wanted}


def test_modality_flags_empty_id_list_returns_empty_dict_without_querying(temp_db):
    """空清單代表「沒有影片要查」，不能退化成「查全部」。"""
    video_id = _make_video()
    _insert_segment_with_modalities(video_id, transcript="甲")

    assert db.modality_flags_by_video([]) == {}


# ----------------------------------------------------------------------
# segments_fts（BM25 關鍵字檢索，見 docs/hybrid-retrieval-bm25-plan.md）
# ----------------------------------------------------------------------


def _insert_segment_with_text(video_id: int, start_sec: float, end_sec: float, visual_description: str) -> int:
    return db.insert_segment(
        video_id=video_id, start_sec=start_sec, end_sec=end_sec,
        transcript=None, visual_description=visual_description, ocr_text=None,
        transcript_embedding=None, visual_embedding=None,
        asr_model="a", vlm_model="v", embedding_model="e",
    )


def test_insert_segment_syncs_fts_table(temp_db):
    video_id = _make_video()
    _insert_segment_with_text(video_id, 0.0, 5.0, "背景有幾輛汽車正在組裝")

    results = db.fts_bm25_search(["汽車正在"])
    assert len(results) == 1


def test_fts_bm25_search_ranks_more_specific_match_first(temp_db):
    video_id = _make_video()
    exact_id = _insert_segment_with_text(video_id, 0.0, 5.0, "一個矩形框架，顯示 FRAME 字樣，畫面簡潔")
    _insert_segment_with_text(video_id, 5.0, 10.0, "機器人在工廠操作零件，背景畫面明亮")

    results = db.fts_bm25_search(["FRAME", "畫面"])
    ranked_ids = [seg_id for seg_id, _ in results]
    assert ranked_ids[0] == exact_id  # 同時命中兩個詞，bm25 分數該排第一


def test_fts_bm25_search_short_query_finds_nothing(temp_db):
    # 鎖住 trigram tokenizer 的已知限制：<3 字元的查詢完全查不到任何結果
    # （不是分數低，是 tokenizer 產生不出任何 trigram），即使內容裡確實
    # 有這個字面文字——這是 search.py 需要 fts_like_search fallback 的原因，
    # 見 db/segments.py create_table 的說明。這個測試如果哪天因為 SQLite
    # 版本升級而失敗（trigram 開始支援 <3 字元），代表 search.py 那層
    # fallback 可以評估要不要簡化。
    video_id = _make_video()
    _insert_segment_with_text(video_id, 0.0, 5.0, "背景有幾輛汽車正在組裝")

    assert db.fts_bm25_search(["汽車"]) == []


def test_fts_like_search_finds_short_term(temp_db):
    video_id = _make_video()
    seg_id = _insert_segment_with_text(video_id, 0.0, 5.0, "背景有幾輛汽車正在組裝")

    assert db.fts_like_search("汽車") == [seg_id]


def test_backfill_fts_covers_pre_existing_rows(temp_db):
    video_id = _make_video()
    with db.get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO segments (video_id, start_sec, end_sec, visual_description, created_at) "
            "VALUES (?, 0.0, 5.0, ?, datetime('now'))",
            (video_id, "一隻雄獅站在淺水中"),
        )
        segment_id = cursor.lastrowid

    with db.get_connection() as conn:
        before = conn.execute("SELECT rowid FROM segments_fts WHERE rowid = ?", (segment_id,)).fetchone()
    assert before is None  # 直接寫 segments 表繞過 insert_segment，segments_fts 還沒有這筆

    with db.get_connection() as conn:
        db.segments.backfill_fts(conn)

    assert db.fts_like_search("雄獅") == [segment_id]
