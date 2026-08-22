"""search_log 表：每次搜尋的實際花費紀錄，見 pipeline/search.py。"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from . import get_connection


def create_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS search_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            cost_usd REAL NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def insert_search_log(query: str, cost_usd: float) -> None:
    created_at = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO search_log (query, cost_usd, created_at) VALUES (?, ?, ?)",
            (query, cost_usd, created_at),
        )
