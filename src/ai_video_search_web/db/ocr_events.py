"""ocr_events 表：本地 OCR（EasyOCR）事件的 schema 與 CRUD。跟 VLM-OCR 的
segments.ocr_text 互補，不是同一批資料，見 docs/ocr-local-engine-plan.md。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from . import get_connection


@dataclass
class OcrEventRecord:
    id: int
    video_id: int
    segment_id: int | None
    start_sec: float
    end_sec: float
    frame_sec: float
    raw_text: str
    resolved_text: str
    confidence: float | None
    bbox: str | None
    primary_engine: str
    ocr_pipeline_version: str
    embedding: bytes | None
    created_at: str


def create_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ocr_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL,
            segment_id INTEGER,
            start_sec REAL NOT NULL,
            end_sec REAL NOT NULL,
            frame_sec REAL NOT NULL,
            raw_text TEXT NOT NULL,
            resolved_text TEXT NOT NULL,
            confidence REAL,
            bbox TEXT,
            primary_engine TEXT NOT NULL,
            ocr_pipeline_version TEXT NOT NULL,
            embedding BLOB,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ocr_events_video_id ON ocr_events(video_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ocr_events_segment_id ON ocr_events(segment_id)")


def insert_ocr_event(
    video_id: int,
    segment_id: int | None,
    start_sec: float,
    end_sec: float,
    frame_sec: float,
    raw_text: str,
    resolved_text: str,
    confidence: float | None,
    bbox: str | None,
    primary_engine: str,
    ocr_pipeline_version: str,
    embedding: bytes | None,
) -> int:
    created_at = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO ocr_events (
                video_id, segment_id, start_sec, end_sec, frame_sec, raw_text, resolved_text,
                confidence, bbox, primary_engine, ocr_pipeline_version, embedding, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                video_id,
                segment_id,
                start_sec,
                end_sec,
                frame_sec,
                raw_text,
                resolved_text,
                confidence,
                bbox,
                primary_engine,
                ocr_pipeline_version,
                embedding,
                created_at,
            ),
        )
        return cursor.lastrowid


def list_ocr_events_for_video(video_id: int) -> list[OcrEventRecord]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM ocr_events WHERE video_id = ? ORDER BY start_sec", (video_id,)
        ).fetchall()
        return [_row_to_ocr_event(row) for row in rows]


def list_all_ocr_events() -> list[OcrEventRecord]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM ocr_events ORDER BY video_id, start_sec").fetchall()
        return [_row_to_ocr_event(row) for row in rows]


def _row_to_ocr_event(row: sqlite3.Row) -> OcrEventRecord:
    return OcrEventRecord(
        id=row["id"],
        video_id=row["video_id"],
        segment_id=row["segment_id"],
        start_sec=row["start_sec"],
        end_sec=row["end_sec"],
        frame_sec=row["frame_sec"],
        raw_text=row["raw_text"],
        resolved_text=row["resolved_text"],
        confidence=row["confidence"],
        bbox=row["bbox"],
        primary_engine=row["primary_engine"],
        ocr_pipeline_version=row["ocr_pipeline_version"],
        embedding=row["embedding"],
        created_at=row["created_at"],
    )
