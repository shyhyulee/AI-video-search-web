"""SQLite 存取層：對外的公開介面與拆套件前完全一樣（`from .. import db;
db.xxx()`），依表拆成 videos／segments／ocr_events／search_log／jobs／
conversations 六個子模組。這個檔案負責連線管理、跨表的 init_db() 統籌，並把
各子模組的公開函式／型別重新匯出成原本的扁平介面。

DB_PATH／get_connection() 刻意只定義在這裡（不是某個子模組）：Python
函式讀取的是「定義它的模組」的全域變數，不是「呼叫它的模組」的，所以
不管從哪個子模組呼叫 get_connection()，測試用
`monkeypatch.setattr(db, "DB_PATH", ...)` 導向臨時檔案都會正確生效。
子模組一律透過 `from . import get_connection` 呼叫，不直接讀 DB_PATH。

get_connection() 開 WAL mode＋較長的 busy_timeout：這個 app 的並發模式是
「多個 HTTP request 同時讀、Job Manager 的 pump thread 與分析流程偶爾寫」
（見 docs/09-web-ui-migration-plan.md），WAL 讓讀者不擋寫者、寫者不擋讀者，
正好對症下藥。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DB_PATH = PROJECT_ROOT / "app.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# 子模組會用 `from . import get_connection` 呼叫回這個檔案，所以要先定義
# 好 get_connection／DB_PATH，才能匯入子模組——順序故意反過來寫。
from . import conversations, jobs, ocr_events, search_log, segments, videos

# 重新匯出：呼叫端原本的 `db.xxx` 用法完全不變。
from .videos import (
    SOURCE_LOCAL,
    SOURCE_YOUTUBE,
    STATUS_ANALYZED,
    STATUS_ANALYZING,
    STATUS_FAILED,
    STATUS_PENDING,
    HeaderStatsData,
    VideoRecord,
    delete_video,
    find_by_source_url,
    get_header_stats,
    get_video,
    insert_video,
    list_analyzed_videos,
    list_library_videos,
    list_pending_videos,
    mark_video_analyzed,
    reset_to_pending,
    update_video_status,
    update_video_summary,
)
from .segments import (
    ModalityFlags,
    SegmentRecord,
    fts_bm25_search,
    fts_like_search,
    insert_segment,
    list_all_segments,
    list_segments_for_video,
    modality_flags_by_video,
)
from .ocr_events import (
    OcrEventRecord,
    insert_ocr_event,
    list_all_ocr_events,
    list_ocr_events_for_video,
)
from .search_log import insert_search_log
from .jobs import (
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_TYPE_ANALYSIS,
    JOB_TYPE_DOWNLOAD,
    JobRecord,
    fail_all_running_jobs,
    get_job,
    has_active_analysis_job,
    has_active_download_job,
    insert_job,
    list_jobs,
    mark_job_completed,
    mark_job_failed,
    mark_job_running,
    set_job_video_id,
    update_job_progress,
)
from .conversations import (
    ConversationRecord,
    get_conversation,
    insert_conversation,
    update_conversation,
)

__all__ = [
    "PROJECT_ROOT", "DB_PATH", "get_connection", "init_db",
    "STATUS_PENDING", "STATUS_ANALYZING", "STATUS_ANALYZED", "STATUS_FAILED",
    "SOURCE_YOUTUBE", "SOURCE_LOCAL",
    "VideoRecord", "HeaderStatsData", "SegmentRecord", "ModalityFlags", "OcrEventRecord",
    "insert_video", "get_video", "find_by_source_url", "list_pending_videos",
    "get_header_stats", "list_analyzed_videos", "list_library_videos",
    "update_video_summary", "reset_to_pending", "delete_video",
    "update_video_status", "mark_video_analyzed",
    "insert_segment", "list_segments_for_video", "list_all_segments", "modality_flags_by_video",
    "fts_bm25_search", "fts_like_search",
    "insert_ocr_event", "list_ocr_events_for_video", "list_all_ocr_events",
    "insert_search_log",
    "JobRecord", "JOB_TYPE_ANALYSIS", "JOB_TYPE_DOWNLOAD",
    "JOB_STATUS_QUEUED", "JOB_STATUS_RUNNING", "JOB_STATUS_COMPLETED", "JOB_STATUS_FAILED",
    "insert_job", "get_job", "list_jobs", "has_active_analysis_job",
    "has_active_download_job", "mark_job_running", "update_job_progress",
    "set_job_video_id", "mark_job_completed", "mark_job_failed", "fail_all_running_jobs",
    "ConversationRecord", "insert_conversation", "get_conversation", "update_conversation",
]


def init_db() -> None:
    with get_connection() as conn:
        videos.create_table(conn)
        segments.create_table(conn)
        ocr_events.create_table(conn)
        search_log.create_table(conn)
        jobs.create_table(conn)
        conversations.create_table(conn)
        videos.migrate_columns(conn)
        segments.migrate_columns(conn)
        segments.backfill_fts(conn)
