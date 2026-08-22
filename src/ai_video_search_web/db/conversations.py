"""conversations 表：把 pipeline.conversation.ConversationState 序列化存到
DB，讓 Web 版的多輪對話能跨 HTTP request（甚至跨伺服器重啟）延續，取代
Tkinter 版本「只存在 Tk widget 實例記憶體」的做法。見
docs/09-web-ui-migration-plan.md 3.2 節。

state_json 存整包序列化後的 ConversationState（見
services/conversation_service.py），不拆欄位：ConversationState 每輪整批
替換（不是累加）且有 _HISTORY_MAX_CHARS=800 的硬性截斷，大小穩定有界，
整包覆寫是便宜的操作，不需要更複雜的正規化設計。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from . import get_connection


@dataclass
class ConversationRecord:
    id: int
    state_json: str
    total_cost_usd: float
    created_at: str
    updated_at: str


def create_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state_json TEXT NOT NULL,
            total_cost_usd REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def insert_conversation(state_json: str) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO conversations (state_json, total_cost_usd, created_at, updated_at) VALUES (?, 0, ?, ?)",
            (state_json, now, now),
        )
        return cursor.lastrowid


def get_conversation(conversation_id: int) -> ConversationRecord | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        return _row_to_record(row) if row else None


def update_conversation(conversation_id: int, state_json: str, additional_cost_usd: float) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE conversations
            SET state_json = ?, total_cost_usd = total_cost_usd + ?, updated_at = ?
            WHERE id = ?
            """,
            (state_json, additional_cost_usd, now, conversation_id),
        )


def _row_to_record(row: sqlite3.Row) -> ConversationRecord:
    return ConversationRecord(
        id=row["id"],
        state_json=row["state_json"],
        total_cost_usd=row["total_cost_usd"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
