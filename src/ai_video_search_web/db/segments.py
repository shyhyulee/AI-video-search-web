"""segments 表：影片片段（字幕／畫面描述／OCR／embedding）的 schema、
migration 與 CRUD。"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from . import get_connection

_SEGMENTS_NEW_COLUMNS = {
    "no_speech_prob": "REAL",
    "avg_logprob": "REAL",
    "compression_ratio": "REAL",
    "ocr_embedding": "BLOB",
    # 這個片段的畫面描述用了幾張畫面產生（1=單幀，2=條件式多幀觸發），見
    # pipeline/analyzer.py MULTI_FRAME_TRIGGER_SEC 旁的說明；NULL 代表這筆
    # 資料是欄位新增前的舊資料，語意上等同單幀（當時只有單幀取樣）。
    "vlm_frame_count": "INTEGER",
}


@dataclass
class SegmentRecord:
    id: int
    video_id: int
    start_sec: float
    end_sec: float
    transcript: str | None
    visual_description: str | None
    ocr_text: str | None
    transcript_embedding: bytes | None
    visual_embedding: bytes | None
    ocr_embedding: bytes | None
    asr_model: str | None
    vlm_model: str | None
    embedding_model: str | None
    created_at: str
    no_speech_prob: float | None
    avg_logprob: float | None
    compression_ratio: float | None
    vlm_frame_count: int | None


def create_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL,
            start_sec REAL NOT NULL,
            end_sec REAL NOT NULL,
            transcript TEXT,
            visual_description TEXT,
            ocr_text TEXT,
            transcript_embedding BLOB,
            visual_embedding BLOB,
            asr_model TEXT,
            vlm_model TEXT,
            embedding_model TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_segments_video_id ON segments(video_id)")
    # BM25 關鍵字檢索索引，見 docs/hybrid-retrieval-bm25-plan.md。tokenize='trigram'
    # 是刻意選的：預設 unicode61 對中文完全無法比對子字串（中文沒有空白斷詞），
    # trigram 才能正確比對中文子字串——代價是查詢字串 <3 字元會完全查不到任何
    # 結果（tokenizer 產生不出 trigram，不是分數低），search.py 那邊用 LIKE
    # fallback 處理短詞。rowid 直接對應 segments.id，靠呼叫端自己保持同步
    # （insert_segment 寫入時同步寫、backfill_fts 補歷史資料），沒有用 FTS5
    # 的 external content 語法，避免多一層需要理解的機制。
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(content, tokenize='trigram')")


def migrate_columns(conn: sqlite3.Connection) -> None:
    """輕量遷移：對已存在的 segments 表補上新欄位（不影響既有資料）。"""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(segments)")}
    for column, sql_type in _SEGMENTS_NEW_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE segments ADD COLUMN {column} {sql_type}")


def backfill_fts(conn: sqlite3.Connection) -> None:
    """把 segments_fts 裡還沒有的既有片段補進去。新片段由 insert_segment()
    當下同步寫入，這裡只處理「這張表剛建出來、還是空的」這種歷史資料情況；
    冪等、每次 init_db() 都可以安全重跑，沒有新資料時幾乎不花時間。"""
    conn.execute(
        """
        INSERT INTO segments_fts (rowid, content)
        SELECT id, COALESCE(transcript, '') || ' ' || COALESCE(visual_description, '') || ' ' || COALESCE(ocr_text, '')
        FROM segments
        WHERE id NOT IN (SELECT rowid FROM segments_fts)
        """
    )


def insert_segment(
    video_id: int,
    start_sec: float,
    end_sec: float,
    transcript: str | None,
    visual_description: str | None,
    ocr_text: str | None,
    transcript_embedding: bytes | None,
    visual_embedding: bytes | None,
    asr_model: str | None,
    vlm_model: str | None,
    embedding_model: str | None,
    ocr_embedding: bytes | None = None,
    no_speech_prob: float | None = None,
    avg_logprob: float | None = None,
    compression_ratio: float | None = None,
    vlm_frame_count: int | None = None,
) -> int:
    created_at = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO segments (
                video_id, start_sec, end_sec, transcript, visual_description, ocr_text,
                transcript_embedding, visual_embedding, ocr_embedding, asr_model, vlm_model,
                embedding_model, no_speech_prob, avg_logprob, compression_ratio, vlm_frame_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                video_id,
                start_sec,
                end_sec,
                transcript,
                visual_description,
                ocr_text,
                transcript_embedding,
                visual_embedding,
                ocr_embedding,
                asr_model,
                vlm_model,
                embedding_model,
                no_speech_prob,
                avg_logprob,
                compression_ratio,
                vlm_frame_count,
                created_at,
            ),
        )
        segment_id = cursor.lastrowid
        content = " ".join(filter(None, [transcript, visual_description, ocr_text]))
        conn.execute("INSERT INTO segments_fts (rowid, content) VALUES (?, ?)", (segment_id, content))
        return segment_id


def list_segments_for_video(video_id: int) -> list[SegmentRecord]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM segments WHERE video_id = ? ORDER BY start_sec", (video_id,)
        ).fetchall()
        return [_row_to_segment(row) for row in rows]


def list_all_segments() -> list[SegmentRecord]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM segments ORDER BY video_id, start_sec").fetchall()
        return [_row_to_segment(row) for row in rows]


def fts_bm25_search(terms: list[str], limit: int = 200) -> list[tuple[int, float]]:
    """對 >=3 字元的關鍵字做 FTS5 OR 查詢，回傳 (segment_id, bm25 分數)——
    分數是 SQLite 原生 bm25()，數字越小（越負）代表越相關。terms 必須都
    是 >=3 字元（trigram tokenizer 的限制，見 create_table 的說明），呼叫端
    負責先過濾。"""
    if not terms:
        return []
    or_query = " OR ".join(f'"{t}"' for t in terms)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT rowid, bm25(segments_fts) FROM segments_fts WHERE segments_fts MATCH ? "
            "ORDER BY bm25(segments_fts) LIMIT ?",
            (or_query, limit),
        ).fetchall()
    return [(row[0], row[1]) for row in rows]


def fts_like_search(term: str, limit: int = 200) -> list[int]:
    """給 <3 字元的關鍵字用的 fallback（trigram tokenizer 查不到，見
    create_table 的說明）：純子字串比對，回傳 segment_id 列表，沒有分數。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT rowid FROM segments_fts WHERE content LIKE ? LIMIT ?",
            (f"%{term}%", limit),
        ).fetchall()
    return [row[0] for row in rows]


def _row_to_segment(row: sqlite3.Row) -> SegmentRecord:
    keys = row.keys()
    return SegmentRecord(
        id=row["id"],
        video_id=row["video_id"],
        start_sec=row["start_sec"],
        end_sec=row["end_sec"],
        transcript=row["transcript"],
        visual_description=row["visual_description"],
        ocr_text=row["ocr_text"],
        transcript_embedding=row["transcript_embedding"],
        visual_embedding=row["visual_embedding"],
        ocr_embedding=row["ocr_embedding"] if "ocr_embedding" in keys else None,
        asr_model=row["asr_model"],
        vlm_model=row["vlm_model"],
        embedding_model=row["embedding_model"],
        created_at=row["created_at"],
        no_speech_prob=row["no_speech_prob"] if "no_speech_prob" in keys else None,
        avg_logprob=row["avg_logprob"] if "avg_logprob" in keys else None,
        compression_ratio=row["compression_ratio"] if "compression_ratio" in keys else None,
        vlm_frame_count=row["vlm_frame_count"] if "vlm_frame_count" in keys else None,
    )
