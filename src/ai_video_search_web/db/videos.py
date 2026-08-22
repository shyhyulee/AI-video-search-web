"""videos 表：影片主表的 schema、migration 與 CRUD。"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from . import get_connection

STATUS_PENDING = "pending"
STATUS_ANALYZING = "analyzing"
STATUS_ANALYZED = "analyzed"
STATUS_FAILED = "failed"

SOURCE_YOUTUBE = "youtube"
SOURCE_LOCAL = "local"

_VIDEOS_NEW_COLUMNS = {
    "asr_model": "TEXT",
    "vlm_model": "TEXT",
    "embedding_model": "TEXT",
    "summary": "TEXT",
    "summary_model": "TEXT",
}


@dataclass
class VideoRecord:
    id: int
    title: str
    source: str
    source_url: str | None
    file_path: str
    duration_sec: int | None
    status: str
    pipeline_stage: str | None
    created_at: str
    analyzed_at: str | None
    segment_count: int | None
    cost_usd: float | None
    asr_model: str | None
    vlm_model: str | None
    embedding_model: str | None
    summary: str | None
    summary_model: str | None


@dataclass
class HeaderStatsData:
    pending_count: int
    analyzed_count: int
    segment_count: int
    total_cost_usd: float


def create_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            source TEXT NOT NULL,
            source_url TEXT,
            file_path TEXT NOT NULL,
            duration_sec INTEGER,
            status TEXT NOT NULL DEFAULT 'pending',
            pipeline_stage TEXT,
            created_at TEXT NOT NULL,
            analyzed_at TEXT,
            segment_count INTEGER,
            cost_usd REAL
        )
        """
    )


def migrate_columns(conn: sqlite3.Connection) -> None:
    """輕量遷移：對已存在的 videos 表補上新欄位（不影響既有資料）。"""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(videos)")}
    for column, sql_type in _VIDEOS_NEW_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE videos ADD COLUMN {column} {sql_type}")


def insert_video(
    title: str,
    source: str,
    source_url: str | None,
    file_path: str,
    duration_sec: int | None,
) -> int:
    created_at = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO videos (title, source, source_url, file_path, duration_sec, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (title, source, source_url, file_path, duration_sec, STATUS_PENDING, created_at),
        )
        return cursor.lastrowid


def get_video(video_id: int) -> VideoRecord | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        return _row_to_record(row) if row else None


def find_by_source_url(source_url: str) -> VideoRecord | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM videos WHERE source_url = ?", (source_url,)).fetchone()
        return _row_to_record(row) if row else None


def list_pending_videos() -> list[VideoRecord]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM videos WHERE status = ? ORDER BY created_at DESC", (STATUS_PENDING,)
        ).fetchall()
        return [_row_to_record(row) for row in rows]


def get_header_stats() -> HeaderStatsData:
    with get_connection() as conn:
        pending_count = conn.execute(
            "SELECT COUNT(*) AS c FROM videos WHERE status = ?", (STATUS_PENDING,)
        ).fetchone()["c"]
        row = conn.execute(
            """
            SELECT COUNT(*) AS c, COALESCE(SUM(segment_count), 0) AS s, COALESCE(SUM(cost_usd), 0) AS cost
            FROM videos WHERE status = ?
            """,
            (STATUS_ANALYZED,),
        ).fetchone()
        return HeaderStatsData(
            pending_count=pending_count,
            analyzed_count=row["c"],
            segment_count=row["s"],
            total_cost_usd=row["cost"],
        )


def list_analyzed_videos() -> list[VideoRecord]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM videos WHERE status = ? ORDER BY analyzed_at DESC", (STATUS_ANALYZED,)
        ).fetchall()
        return [_row_to_record(row) for row in rows]


def list_library_videos() -> list[VideoRecord]:
    """「影片庫」頁籤用：分析完成與分析失敗的影片都要能看到。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM videos WHERE status IN (?, ?) ORDER BY analyzed_at DESC, created_at DESC",
            (STATUS_ANALYZED, STATUS_FAILED),
        ).fetchall()
        return [_row_to_record(row) for row in rows]


def update_video_summary(video_id: int, summary: str, summary_model: str, additional_cost_usd: float) -> None:
    """設定摘要並把這次產生摘要的花費累加進 cost_usd（可重複呼叫＝重新產生摘要）。"""
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE videos
            SET summary = ?, summary_model = ?, cost_usd = COALESCE(cost_usd, 0) + ?
            WHERE id = ?
            """,
            (summary, summary_model, additional_cost_usd, video_id),
        )


def reset_to_pending(video_id: int) -> None:
    """把卡住／失敗的分析還原成 pending：清掉部分寫入的 segments、ocr_events 與所有分析欄位。

    直接用 DELETE FROM segments／ocr_events（不是呼叫 segments.py／
    ocr_events.py 的函式）是刻意的：這樣才能跟 videos 表的 UPDATE 落在
    同一個 get_connection() 交易裡，video 更新失敗時 segments／ocr_events
    的刪除也會一起回滾，維持原子性。
    """
    with get_connection() as conn:
        conn.execute("DELETE FROM segments WHERE video_id = ?", (video_id,))
        conn.execute("DELETE FROM ocr_events WHERE video_id = ?", (video_id,))
        conn.execute(
            """
            UPDATE videos
            SET status = ?, pipeline_stage = NULL, analyzed_at = NULL, segment_count = NULL,
                cost_usd = NULL, asr_model = NULL, vlm_model = NULL, embedding_model = NULL,
                summary = NULL, summary_model = NULL
            WHERE id = ?
            """,
            (STATUS_PENDING, video_id),
        )


def delete_video(video_id: int) -> VideoRecord | None:
    """同樣直接用 DELETE FROM segments／ocr_events，理由見 reset_to_pending()。"""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM segments WHERE video_id = ?", (video_id,))
        conn.execute("DELETE FROM ocr_events WHERE video_id = ?", (video_id,))
        conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        return _row_to_record(row)


def update_video_status(video_id: int, status: str, pipeline_stage: str | None = None) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE videos SET status = ?, pipeline_stage = ? WHERE id = ?",
            (status, pipeline_stage, video_id),
        )


def mark_video_analyzed(
    video_id: int,
    segment_count: int,
    cost_usd: float,
    asr_model: str,
    vlm_model: str,
    embedding_model: str,
    pipeline_stage: str | None = None,
    summary: str | None = None,
    summary_model: str | None = None,
) -> None:
    """summary／summary_model 是自動摘要（Phase F）寫入用的可選欄位；不傳
    （None）就用 COALESCE 保留原本的值，不會覆蓋掉既有摘要（例如重新分析
    但這次自動摘要失敗的情況）。
    """
    analyzed_at = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE videos
            SET status = ?, pipeline_stage = ?, analyzed_at = ?, segment_count = ?,
                cost_usd = ?, asr_model = ?, vlm_model = ?, embedding_model = ?,
                summary = COALESCE(?, summary), summary_model = COALESCE(?, summary_model)
            WHERE id = ?
            """,
            (
                STATUS_ANALYZED,
                pipeline_stage,
                analyzed_at,
                segment_count,
                cost_usd,
                asr_model,
                vlm_model,
                embedding_model,
                summary,
                summary_model,
                video_id,
            ),
        )


def _row_to_record(row: sqlite3.Row) -> VideoRecord:
    keys = row.keys()
    return VideoRecord(
        id=row["id"],
        title=row["title"],
        source=row["source"],
        source_url=row["source_url"],
        file_path=row["file_path"],
        duration_sec=row["duration_sec"],
        status=row["status"],
        pipeline_stage=row["pipeline_stage"],
        created_at=row["created_at"],
        analyzed_at=row["analyzed_at"],
        segment_count=row["segment_count"],
        cost_usd=row["cost_usd"],
        asr_model=row["asr_model"] if "asr_model" in keys else None,
        vlm_model=row["vlm_model"] if "vlm_model" in keys else None,
        embedding_model=row["embedding_model"] if "embedding_model" in keys else None,
        summary=row["summary"] if "summary" in keys else None,
        summary_model=row["summary_model"] if "summary_model" in keys else None,
    )
