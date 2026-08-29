"""把測試資料庫填成一組固定的假影片，供前端 smoke 測試使用。

為什麼要固定的假資料而不是直接連正式資料庫：smoke 會斷言「影片庫有 4 支」
「『科技與製造』這顆 chip 存在」這類具體的東西，連正式庫的話，你一加影片或
重新分析，smoke 就會轉紅——那是資料變了，不是程式壞了。可重現比「看到真實
內容」重要，畢竟這支測試的用途是「改壞了要叫」。

**安全防護**：跟 tests/conftest.py 同一道——目標資料庫名稱必須以 `_test`
結尾才動手。這不是形式檢查，這支腳本會 TRUNCATE。

用法（一般不用手動跑，playwright.config.ts 會自動執行）：

    uv run python scripts/seed_smoke_db.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from ai_video_search_web import db

_TEST_SUFFIX = "_test"
_TABLES = ["videos", "segments", "ocr_events", "search_log", "jobs", "conversations"]

# 固定的四支影片，每一支都在 smoke 裡有具體用途：
#   - 兩支已分析、分屬不同主題分類（影片庫的 chips 至少要有兩顆才看得出分類有效）
#   - 一支分析失敗（狀態篩選的另一個分支）
#   - 一支待分析（「影片與分析」頁才不會是空清單）
# 標題與摘要的用詞會被 frontend/src/lib/videoCategory.ts 的關鍵字規則吃到，
# 改這裡的文字前先看那份規則，否則 chip 的名稱會跟著變、smoke 就對不上了。
_VIDEOS = [
    {
        "title": "半導體晶片工廠產線導覽",
        "summary": "這支影片帶觀眾走過一條半導體晶片的生產線，從晶圓進料、光刻、蝕刻到封裝測試，"
                   "說明每個製程階段的設備與作業重點。",
        "status": db.STATUS_ANALYZED,
        "duration_sec": 620,
        "cost_usd": 0.18,
        "segments": [
            ("晶圓進料區的自動搬運系統", "首先我們看到的是晶圓進料", "STAGE 1"),
            ("光刻機正在曝光晶圓", "接著進入光刻製程", "STAGE 2"),
            ("封裝測試區的檢測設備", "最後是封裝與測試", None),
        ],
    },
    {
        "title": "線性代數：向量與矩陣入門",
        "summary": "這是一堂線性代數的入門課程，講解向量的幾何意義、矩陣乘法的運算規則，"
                   "以及它們在座標轉換上的應用。",
        "status": db.STATUS_ANALYZED,
        "duration_sec": 1450,
        "cost_usd": 0.31,
        "segments": [
            ("白板上畫著二維座標與向量箭頭", "向量可以想成有方向的箭頭", None),
            ("投影片顯示矩陣乘法的算式", "矩陣乘法不滿足交換律", "A × B ≠ B × A"),
        ],
    },
    {
        "title": "分析失敗的測試影片",
        "summary": None,
        "status": db.STATUS_FAILED,
        "duration_sec": 90,
        "cost_usd": None,
        "segments": [],
    },
    {
        "title": "還沒分析的測試影片",
        "summary": None,
        "status": db.STATUS_PENDING,
        "duration_sec": 240,
        "cost_usd": None,
        "segments": [],
    },
    {
        # 專門給「移除」那支 smoke 用的犧牲品。刪除是全站唯一**不花錢**的
        # mutation，也是唯一能在 smoke 裡驗到 react-query invalidation 有沒有
        # 接對的路徑——query key 打錯時清單照樣載入得起來（換個 key 還是會呼叫
        # 同一個 queryFn），只有 invalidation 會失效，所以非有這條不可。
        "title": "可移除的測試影片",
        "summary": None,
        "status": db.STATUS_PENDING,
        "duration_sec": 60,
        "cost_usd": None,
        "segments": [],
    },
]


def _guard(dsn: str) -> str:
    name = conninfo_to_dict(dsn).get("dbname", "")
    if not name.endswith(_TEST_SUFFIX):
        raise SystemExit(
            f"拒絕操作非測試資料庫：{name!r}（名稱必須以 {_TEST_SUFFIX} 結尾）。"
            "這支腳本會 TRUNCATE，不能讓它打到正式資料庫。"
        )
    return name


def _smoke_dsn() -> str:
    """測試資料庫的連線字串，推導方式跟 tests/conftest.py 完全一樣。

    **不能讀 `DATABASE_URL`**：`db` 模組載入時就 `load_dotenv()` 了，那個變數
    這時已經是正式資料庫的位址，讀它等於預設打到正式庫（第一次寫成這樣，被
    上面的 `_guard()` 擋下來了）。要覆寫請用 `TEST_DATABASE_URL`，跟 pytest
    同一個慣例，見 .env.example。
    """
    override = os.environ.get("TEST_DATABASE_URL")
    if override:
        return override
    name = conninfo_to_dict(db.DSN).get("dbname", "avs")
    return make_conninfo(db.DSN, dbname=f"{name}{_TEST_SUFFIX}")


def main() -> None:
    dsn = _smoke_dsn()
    name = _guard(dsn)

    # 資料庫可能還不存在（例如從沒跑過 pytest 的環境）；CREATE DATABASE 不能在
    # 交易裡執行，所以連到 postgres 維護資料庫、開 autocommit。
    admin = make_conninfo(dsn, dbname="postgres")
    with psycopg.connect(admin, autocommit=True, connect_timeout=10) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            conn.execute(f'CREATE DATABASE "{name}"')

    db.DSN = dsn
    db.init_db()

    with db.get_connection() as conn:
        conn.execute(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE")

    for index, item in enumerate(_VIDEOS, start=1):
        # 用索引而不是 hash(title)：str 的 hash 每個 process 都不一樣
        # （PYTHONHASHSEED 隨機化），那樣 source_url 每次跑都會變。
        slug = f"smoke{index:02d}"
        video_id = db.insert_video(
            title=item["title"],
            source=db.SOURCE_YOUTUBE,
            source_url=f"https://www.youtube.com/watch?v={slug}",
            # 檔案刻意不存在：smoke 不播放影片、不抓縮圖，只看清單與面板
            file_path=f"/nonexistent/{slug}.mp4",
            duration_sec=item["duration_sec"],
        )
        for seg_index, (visual, transcript, ocr) in enumerate(item["segments"]):
            db.insert_segment(
                video_id=video_id,
                start_sec=float(seg_index * 10),
                end_sec=float(seg_index * 10 + 10),
                transcript=transcript,
                visual_description=visual,
                ocr_text=ocr,
                transcript_embedding=None,
                visual_embedding=None,
                ocr_embedding=None,
                asr_model="whisper-1",
                vlm_model="gpt-4o-mini",
                embedding_model="text-embedding-3-small",
            )
        if item["status"] == db.STATUS_ANALYZED:
            db.mark_video_analyzed(
                video_id=video_id,
                segment_count=len(item["segments"]),
                cost_usd=item["cost_usd"],
                asr_model="whisper-1",
                vlm_model="gpt-4o-mini",
                embedding_model="text-embedding-3-small",
                summary=item["summary"],
                summary_model="gpt-4o-mini",
            )
        elif item["status"] != db.STATUS_PENDING:
            db.update_video_status(video_id, item["status"], "分析失敗：測試用資料")

    print(f"已把 {name} 填成 {len(_VIDEOS)} 支固定影片")


if __name__ == "__main__":
    main()
