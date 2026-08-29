"""PostgreSQL 存取層：對外的公開介面與拆套件前完全一樣（`from .. import db;
db.xxx()`），依表拆成 videos／segments／ocr_events／search_log／jobs／
conversations 六個子模組。這個檔案負責連線管理、跨表的 init_db() 統籌，並把
各子模組的公開函式／型別重新匯出成原本的扁平介面。

原本是 SQLite，2026-08 遷移到 PostgreSQL，見
docs/14-postgresql-migration-plan.md。呼叫端（services／pipeline／api）的
程式碼一行都沒有因此改動——這層的函式介面就是為了這種抽換而存在的。

DSN／get_connection() 刻意只定義在這裡（不是某個子模組）：Python
函式讀取的是「定義它的模組」的全域變數，不是「呼叫它的模組」的，所以
不管從哪個子模組呼叫 get_connection()，測試用
`monkeypatch.setattr(db, "DSN", ...)` 導向測試資料庫都會正確生效。
子模組一律透過 `from . import get_connection` 呼叫，不直接讀 DSN。
（遷移前這個變數叫 DB_PATH、指向一個檔案路徑，機制完全相同。）

row_factory 用 dict_row：psycopg 預設回傳 tuple，而全部子模組的
_row_to_record() 都是用 `row["欄位名"]` 取值、部分還會用 `row.keys()` 判斷
欄位存不存在。dict_row 回傳的 dict 兩種用法都支援，抽換連線層就不用動
那六支轉換函式。

連線策略維持「每次呼叫開一條、用完關掉」（跟 SQLite 時期一樣，靠
`with get_connection()` 收尾）。PostgreSQL 走 TCP，每條連線比 SQLite 開檔
貴一些（實測個位數毫秒），以這個 app 的規模可以接受；真的變成瓶頸再引入
psycopg_pool，不要為了還沒發生的問題先加一層。

注意 `with conn` 的語意跟 sqlite3 不同：sqlite3 只 commit 不 close（其實
會漏連線），psycopg 是 commit 之後**連 connection 一起關掉**。這正是我們
要的行為，但也代表 conn 不能在 `with` 區塊外繼續使用。
"""
from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# 這一層自己載 .env，不依賴呼叫端或 pipeline/openai_client.py 先載過：
# scripts/ 底下的工具、pytest、uvicorn 進入點各自不同，靠別人載會有順序問題。
# load_dotenv 預設不覆寫已存在的環境變數，所以外部指定的 DATABASE_URL 優先。
load_dotenv(PROJECT_ROOT / ".env")

# 預設值跟 docker-compose.yml 對齊，讓沒有 .env 的環境（例如剛 clone 下來）
# 也能直接連上本機容器。
DSN = os.environ.get("DATABASE_URL", "postgresql://avs:avs_local_dev@localhost:5433/avs")


def get_connection() -> psycopg.Connection:
    return psycopg.connect(DSN, row_factory=dict_row, connect_timeout=30)


# 子模組會用 `from . import get_connection` 呼叫回這個檔案，所以要先定義
# 好 get_connection／DSN，才能匯入子模組——順序故意反過來寫。
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
    clear_analysis_output,
    delete_video,
    find_by_source_url,
    get_header_stats,
    get_video,
    insert_video,
    list_analyzed_videos,
    list_library_videos,
    list_unanalyzed_videos,
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
    list_segments_for_videos,
    modality_flags_by_video,
)
from .ocr_events import (
    OcrEventRecord,
    insert_ocr_event,
    list_all_ocr_events,
    list_ocr_events_for_video,
    list_ocr_events_for_videos,
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
    list_active_jobs,
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
    "PROJECT_ROOT", "DSN", "get_connection", "init_db",
    "STATUS_PENDING", "STATUS_ANALYZING", "STATUS_ANALYZED", "STATUS_FAILED",
    "SOURCE_YOUTUBE", "SOURCE_LOCAL",
    "VideoRecord", "HeaderStatsData", "SegmentRecord", "ModalityFlags", "OcrEventRecord",
    "insert_video", "get_video", "find_by_source_url", "list_unanalyzed_videos",
    "get_header_stats", "list_analyzed_videos", "list_library_videos",
    "update_video_summary", "reset_to_pending", "delete_video", "clear_analysis_output",
    "update_video_status", "mark_video_analyzed",
    "insert_segment", "list_segments_for_video", "list_segments_for_videos", "list_all_segments",
    "modality_flags_by_video",
    "fts_bm25_search", "fts_like_search",
    "insert_ocr_event", "list_ocr_events_for_video", "list_ocr_events_for_videos",
    "list_all_ocr_events",
    "insert_search_log",
    "JobRecord", "JOB_TYPE_ANALYSIS", "JOB_TYPE_DOWNLOAD",
    "JOB_STATUS_QUEUED", "JOB_STATUS_RUNNING", "JOB_STATUS_COMPLETED", "JOB_STATUS_FAILED",
    "insert_job", "get_job", "list_jobs", "list_active_jobs", "has_active_analysis_job",
    "has_active_download_job", "mark_job_running", "update_job_progress",
    "set_job_video_id", "mark_job_completed", "mark_job_failed", "fail_all_running_jobs",
    "ConversationRecord", "insert_conversation", "get_conversation", "update_conversation",
]


def init_db() -> None:
    """建立所有資料表與索引。冪等，每次啟動都可以安全重跑。

    SQLite 時期這裡還要多做四件事，遷移之後全部不需要了：
      - videos.migrate_columns()／segments.migrate_columns()：對既有資料庫後補
        欄位。PostgreSQL 的 create_table() 一次定義齊全，沒有「缺欄位的舊
        資料庫」這種東西。
      - segments.backfill_fts()：把既有片段補進 FTS 索引。
      - segments.prune_orphan_fts()：清掉 FTS 裡對不到片段的殘留列。
    後兩者是因為 FTS5 虛擬表的 rowid 得靠呼叫端自己同步才需要存在；改用
    generated column 之後由資料庫自己維護，那類殘留在結構上不可能發生。
    見 docs/14-postgresql-migration-plan.md §5.2。
    """
    with get_connection() as conn:
        # segments 的中文關鍵字索引需要 pg_trgm。放在這裡而不是只寫在文件裡，
        # 剛 clone 下來的環境跑 init_db() 就能直接建起完整 schema。
        conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        # 建表順序有意義：segments／ocr_events 的 video_id 外鍵指向 videos，
        # videos 必須先存在。
        videos.create_table(conn)
        segments.create_table(conn)
        ocr_events.create_table(conn)
        search_log.create_table(conn)
        jobs.create_table(conn)
        conversations.create_table(conn)
