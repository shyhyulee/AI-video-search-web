"""jobs 表：Category A（downloader／analyzer）背景工作的持久化進度紀錄，讓
Web 版在多個 HTTP request 之間、甚至伺服器重啟後都能查詢工作狀態，取代
Tkinter 版本「只存在記憶體 queue.Queue」的做法。見
docs/09-web-ui-migration-plan.md 3.2 節。

狀態集合刻意只有 queued/running/completed/failed 四種：pipeline 完全沒有
checkpoint／取消 token，做「真取消」要把訊號貫穿進每個 phase 函式，超出這次
遷移的合理範圍，所以不做 retrying／cancelled 這種需要底層配合才有意義的狀態
（見計畫文件 3.2 節「Retry／Cancel 範圍刻意縮小」）。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from . import get_connection

JOB_TYPE_DOWNLOAD = "download"
JOB_TYPE_ANALYSIS = "analysis"

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"


@dataclass
class JobRecord:
    id: int
    job_type: str
    video_id: int | None
    source_url: str | None
    status: str
    stage: str | None
    progress_percent: int | None
    progress_message: str | None
    error_message: str | None
    cost_usd: float | None
    created_at: str
    started_at: str | None
    completed_at: str | None


def create_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_type TEXT NOT NULL,
            video_id INTEGER,
            source_url TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            stage TEXT,
            progress_percent INTEGER,
            progress_message TEXT,
            error_message TEXT,
            cost_usd REAL,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_video_id ON jobs(video_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")


def insert_job(job_type: str, video_id: int | None = None, source_url: str | None = None) -> int:
    created_at = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO jobs (job_type, video_id, source_url, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_type, video_id, source_url, JOB_STATUS_QUEUED, created_at),
        )
        return cursor.lastrowid


def get_job(job_id: int) -> JobRecord | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_record(row) if row else None


def list_jobs(
    video_id: int | None = None, job_type: str | None = None, status: str | None = None
) -> list[JobRecord]:
    query = "SELECT * FROM jobs WHERE 1=1"
    params: list[object] = []
    if video_id is not None:
        query += " AND video_id = ?"
        params.append(video_id)
    if job_type is not None:
        query += " AND job_type = ?"
        params.append(job_type)
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC"
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [_row_to_record(row) for row in rows]


def has_active_analysis_job(video_id: int) -> bool:
    """是否已有排隊中／進行中的分析 job，供 submit 端擋重複觸發同一支影片。"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE video_id = ? AND job_type = ? AND status IN (?, ?) LIMIT 1",
            (video_id, JOB_TYPE_ANALYSIS, JOB_STATUS_QUEUED, JOB_STATUS_RUNNING),
        ).fetchone()
        return row is not None


def has_active_download_job(source_url: str) -> bool:
    """是否已有排隊中／進行中的下載 job；下載完成前 video_id 還不存在，只能
    用 source_url 當 dedup key。"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE source_url = ? AND job_type = ? AND status IN (?, ?) LIMIT 1",
            (source_url, JOB_TYPE_DOWNLOAD, JOB_STATUS_QUEUED, JOB_STATUS_RUNNING),
        ).fetchone()
        return row is not None


def mark_job_running(job_id: int) -> None:
    started_at = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, started_at = ? WHERE id = ?",
            (JOB_STATUS_RUNNING, started_at, job_id),
        )


def update_job_progress(
    job_id: int, stage: str, progress_percent: int | None = None, progress_message: str | None = None
) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE jobs SET stage = ?, progress_percent = ?, progress_message = ? WHERE id = ?",
            (stage, progress_percent, progress_message, job_id),
        )


def set_job_video_id(job_id: int, video_id: int) -> None:
    """下載完成後才知道 video_id，回填給 download job。"""
    with get_connection() as conn:
        conn.execute("UPDATE jobs SET video_id = ? WHERE id = ?", (video_id, job_id))


def mark_job_completed(job_id: int, cost_usd: float | None = None) -> None:
    completed_at = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, cost_usd = ?, completed_at = ? WHERE id = ?",
            (JOB_STATUS_COMPLETED, cost_usd, completed_at, job_id),
        )


def mark_job_failed(job_id: int, error_message: str) -> None:
    completed_at = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, error_message = ?, completed_at = ? WHERE id = ?",
            (JOB_STATUS_FAILED, error_message, completed_at, job_id),
        )


def fail_all_running_jobs(error_message: str) -> int:
    """伺服器啟動時的 reconciliation：把上次異常中止、卡在 running 的 job
    全部標記失敗，回傳受影響筆數。見 docs/09-web-ui-migration-plan.md 3.2 節
    「Zombie job」。
    """
    completed_at = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE jobs SET status = ?, error_message = ?, completed_at = ? WHERE status = ?",
            (JOB_STATUS_FAILED, error_message, completed_at, JOB_STATUS_RUNNING),
        )
        return cursor.rowcount


def _row_to_record(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        id=row["id"],
        job_type=row["job_type"],
        video_id=row["video_id"],
        source_url=row["source_url"],
        status=row["status"],
        stage=row["stage"],
        progress_percent=row["progress_percent"],
        progress_message=row["progress_message"],
        error_message=row["error_message"],
        cost_usd=row["cost_usd"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )
