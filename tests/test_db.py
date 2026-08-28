"""db 套件的特徵測試（characterization tests）：鎖住現有的 schema、
COALESCE 寫入語意、級聯刪除、CRUD 行為，做為之後改動 db 套件的安全網。

隔離方式見 tests/conftest.py：整個 session 共用一個獨立的**測試資料庫**
（`avs_test`），每個測試開始前由 `temp_db` fixture TRUNCATE 清空。
遷移到 PostgreSQL 之前這裡用的是「每個測試一個臨時 SQLite 檔案」，
效果相同（空表、id 從 1 開始），而且一樣碰不到正式資料庫。
"""
from __future__ import annotations

import pytest

from ai_video_search_web import db


def _make_video(title: str = "測試影片", duration_sec: int = 100) -> int:
    return db.insert_video(
        title=title, source=db.SOURCE_LOCAL, source_url=None,
        file_path="/nonexistent.mp4", duration_sec=duration_sec,
    )


# ----------------------------------------------------------------------
# init_db() / migration
# ----------------------------------------------------------------------


def _table_names() -> set[str]:
    with db.get_connection() as conn:
        return {row["tablename"] for row in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}


def _column_names(table: str) -> set[str]:
    with db.get_connection() as conn:
        return {row["column_name"] for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s", (table,))}


def test_init_db_creates_all_tables(temp_db):
    assert {"videos", "segments", "ocr_events", "search_log"} <= _table_names()


def test_init_db_is_idempotent(temp_db):
    # 重複呼叫不該出錯（CREATE TABLE / CREATE INDEX / CREATE EXTENSION 都是 IF NOT EXISTS）
    db.init_db()
    db.init_db()


def test_init_db_creates_every_column_up_front(temp_db):
    """SQLite 時期這些欄位是靠 migrate_columns() 對既有資料庫後補的，這支測試
    當時叫 test_init_db_adds_migrated_columns。PostgreSQL 是全新資料庫，
    create_table() 一次定義齊全，那個機制已經移除——但「這些欄位必須存在」
    這件事本身還是要鎖住，所以測試留著、只換掉檢查方式。
    """
    assert {"asr_model", "vlm_model", "embedding_model", "summary", "summary_model"} <= _column_names("videos")
    assert {"no_speech_prob", "avg_logprob", "compression_ratio", "ocr_embedding",
            "vlm_frame_count"} <= _column_names("segments")


def test_segments_fts_table_is_gone(temp_db):
    """FTS5 虛擬表已經被 segments.content 這個 generated column 取代。
    鎖住這件事，避免哪天有人「順手」把它加回來——那會讓同步問題重新出現。
    """
    assert "segments_fts" not in _table_names()
    assert "content" in _column_names("segments")


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
# 檢索索引與片段的一致性。
#
# SQLite 時期這一節鎖的是「每一條刪除片段的路徑都必須記得把 segments_fts
# 的對應列一起清掉」——那張 FTS5 虛擬表沒有用 external content，rowid 靠
# 呼叫端自己維護，漏掉就會留下殘留列，佔掉 fts_bm25_search() 的前 200 名額、
# 把真正命中的片段擠出候選集（實測曾有 925/1795、52% 是殘留列）。
#
# 遷移到 PostgreSQL 之後 content 是 segments 上的 generated column，跟著同一
# 列生滅，殘留在結構上不可能發生。測試留著、意圖不變（刪掉片段就搜不到了），
# 只是不再需要另外數殘留列——改成直接驗證那個結構性保證。
# ----------------------------------------------------------------------
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
def test_deleting_segments_also_clears_search_index(temp_db, delete_path):
    video_id = _make_video()
    _insert_searchable_segment(video_id, "獨特關鍵字內容")
    assert db.fts_bm25_search(["獨特關鍵字內容"]) != []

    delete_path(video_id)

    assert db.fts_bm25_search(["獨特關鍵字內容"]) == []


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


def test_search_index_cannot_go_orphan(temp_db):
    """取代 SQLite 時期的 test_prune_orphan_fts_removes_rows_without_segment()。

    當時那支測試要證明的是「殘留列清得掉」，前提是殘留列有可能存在——繞過
    insert_segment()／delete_for_video() 直接動 segments 表就會產生。現在
    content 是同一列上的 generated column，用同樣的手法（直接下 SQL 刪除）
    也不可能讓索引與片段脫節，所以改成證明這個結構性保證。
    """
    video_id = _make_video()
    segment_id = _insert_searchable_segment(video_id, "會被偷偷刪掉的片段")
    assert db.fts_like_search("偷偷") == [segment_id]

    # 完全繞過 db 模組的刪除路徑，直接對表下手——舊架構下這正是製造殘留列的方法。
    with db.get_connection() as conn:
        conn.execute("DELETE FROM segments WHERE id = %s", (segment_id,))

    assert db.fts_like_search("偷偷") == []
    assert db.fts_bm25_search(["會被偷偷刪掉的片段"]) == []


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
# 關鍵字檢索（BM25，見 docs/02-technical-decisions.md#搜尋）。
# 底層從 SQLite FTS5 換成 pg_trgm＋SQL 手算 BM25，見 db/segments.py。
# ----------------------------------------------------------------------


def _insert_segment_with_text(video_id: int, start_sec: float, end_sec: float, visual_description: str) -> int:
    return db.insert_segment(
        video_id=video_id, start_sec=start_sec, end_sec=end_sec,
        transcript=None, visual_description=visual_description, ocr_text=None,
        transcript_embedding=None, visual_embedding=None,
        asr_model="a", vlm_model="v", embedding_model="e",
    )


def test_insert_segment_is_searchable_immediately(temp_db):
    """SQLite 時期這支叫 test_insert_segment_syncs_fts_table：insert_segment()
    必須記得多寫一筆進 segments_fts。現在 content 是 generated column，
    插入片段就自動可搜尋——行為相同，但不再依賴呼叫端記得做什麼。
    """
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


def test_fts_bm25_search_short_query_now_finds_results(temp_db):
    """這支測試的斷言在遷移時**反過來了**，是刻意的。

    SQLite 版本鎖的是 FTS5 trigram tokenizer 的硬限制：<3 字元的查詢完全查不到
    任何結果（產不出 token），所以 sparse.py 才需要 fts_like_search() fallback。
    當時的註解就預告了「如果哪天這個限制消失，代表那層 fallback 可以評估要不要
    簡化」——遷移到 PostgreSQL 正是那一天：`ILIKE '%汽車%'` 本來就找得到，
    只是 2 字元的 pattern 抽不出完整 trigram、用不到 GIN 索引而已（實測見
    docs/14-postgresql-migration-plan.md §5.2.1、§10 的 EXPLAIN 結果）。

    **但 sparse.py 這次刻意沒有跟著簡化**：讓短詞從「哨兵分數」變成「真實 IDF
    分數」是搜尋排名的行為變更，會讓 golden set 的差異無法歸因於遷移本身。
    這支測試存在的意義是把這個已知落差寫下來——之後真的要簡化 sparse.py 時，
    這裡就是起點。
    """
    video_id = _make_video()
    _insert_segment_with_text(video_id, 0.0, 5.0, "背景有幾輛汽車正在組裝")

    assert len(db.fts_bm25_search(["汽車"])) == 1


def test_fts_like_search_finds_short_term(temp_db):
    video_id = _make_video()
    seg_id = _insert_segment_with_text(video_id, 0.0, 5.0, "背景有幾輛汽車正在組裝")

    assert db.fts_like_search("汽車") == [seg_id]


def test_raw_insert_is_searchable_without_backfill(temp_db):
    """取代 SQLite 時期的 test_backfill_fts_covers_pre_existing_rows()。

    當時要證明的是 backfill_fts() 補得回來——因為繞過 insert_segment() 直接寫
    segments 表，segments_fts 不會有對應的列，那筆片段就是搜不到。現在 content
    是 generated column，資料庫在 INSERT 當下就算好了，不需要任何補救步驟。
    """
    video_id = _make_video()
    with db.get_connection() as conn:
        segment_id = conn.execute(
            "INSERT INTO segments (video_id, start_sec, end_sec, visual_description, created_at) "
            "VALUES (%s, 0.0, 5.0, %s, now()::text) RETURNING id",
            (video_id, "一隻雄獅站在淺水中"),
        ).fetchone()["id"]

    assert db.fts_like_search("雄獅") == [segment_id]
