"""測試共用的 PostgreSQL 基礎設施。

遷移到 PostgreSQL 之前，每個測試用 `monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")`
拿到一個全新的 SQLite 檔案，隔離是免費的。PostgreSQL 沒有「臨時檔案」這種東西，
所以改成：整個測試 session 共用一個**獨立的測試資料庫**，每個測試開始前
`TRUNCATE ... RESTART IDENTITY` 把它清空——效果一樣（空表、id 從 1 開始），
成本也低（空表的 TRUNCATE 是常數時間）。

資料庫名稱是正式資料庫名稱加上 `_test` 尾綴（預設 `avs` → `avs_test`），
可以用 `TEST_DATABASE_URL` 環境變數整個覆寫。跑完不會刪掉，方便測試失敗後
直接連進去看留下什麼。

**安全防護**：`_truncate_all()` 會先確認目標資料庫名稱以 `_test` 結尾才動手。
這不是形式檢查——正式資料庫 `avs` 裝著真的影片分析結果，如果哪天有人改壞了
DSN 的組法、或忘了掛 fixture，沒有這道防護就是一次無聲的資料全毀。
"""
from __future__ import annotations

import os

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from ai_video_search_web import db

# 跟 db.init_db() 的建表清單一致；TRUNCATE 一次列出所有表，不用管外鍵順序。
_ALL_TABLES = ["videos", "segments", "ocr_events", "search_log", "jobs", "conversations"]

_TEST_DB_SUFFIX = "_test"


def _test_dsn() -> str:
    """測試資料庫的連線字串。用 psycopg 的 conninfo 工具解析／重組，不自己
    對 URL 做字串處理——DSN 也可能是 `host=... dbname=...` 的 keyword 形式。
    """
    override = os.environ.get("TEST_DATABASE_URL")
    if override:
        return override
    name = conninfo_to_dict(db.DSN).get("dbname", "avs")
    return make_conninfo(db.DSN, dbname=f"{name}{_TEST_DB_SUFFIX}")


def _dbname(dsn: str) -> str:
    return conninfo_to_dict(dsn).get("dbname", "")


@pytest.fixture(scope="session", autouse=True)
def _pg_test_database():
    """建立（如果還沒有）測試資料庫，把 db.DSN 指過去，建好 schema。

    autouse＋session scope：所有測試都必須落在測試資料庫上，不能讓任何一支
    測試有機會連到正式資料庫。
    """
    dsn = _test_dsn()
    name = _dbname(dsn)
    if not name.endswith(_TEST_DB_SUFFIX):
        pytest.exit(
            f"測試資料庫名稱必須以 {_TEST_DB_SUFFIX} 結尾，實際是 {name!r}。"
            "拒絕在可能是正式資料庫的地方跑測試。",
            returncode=1,
        )

    # CREATE DATABASE 不能在交易裡執行，所以要 autocommit；連到 postgres
    # 這個維護資料庫下指令（不能連到自己正要建立的那個）。
    admin_dsn = make_conninfo(db.DSN, dbname="postgres")
    try:
        with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=10) as conn:
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
            if not exists:
                conn.execute(f'CREATE DATABASE "{name}"')
    except psycopg.OperationalError as exc:
        pytest.exit(
            f"連不上 PostgreSQL（{admin_dsn}）：{exc}\n"
            "測試需要資料庫在跑，請先 `docker compose up -d`。",
            returncode=1,
        )

    original = db.DSN
    db.DSN = dsn
    db.init_db()
    yield dsn
    db.DSN = original


@pytest.fixture
def clean_db(_pg_test_database):
    """把測試資料庫清空，回到「六張表都是空的、id 從 1 開始」的狀態。

    對應舊版「每個測試一個新的 SQLite 檔案」。RESTART IDENTITY 是必要的：
    不少測試會斷言 `insert_video()` 回傳的 id 或依賴 id 的先後順序。
    """
    name = _dbname(db.DSN)
    if not name.endswith(_TEST_DB_SUFFIX):
        raise RuntimeError(f"拒絕 TRUNCATE 非測試資料庫：{name!r}")
    with db.get_connection() as conn:
        conn.execute(f"TRUNCATE {', '.join(_ALL_TABLES)} RESTART IDENTITY CASCADE")
    return db.DSN


@pytest.fixture
def temp_db(clean_db):
    """沿用舊名稱，讓大部分測試模組不用改動任何一行測試本體。

    需要額外 patch（VIDEO_DIR、job_manager 狀態）的模組會自己定義同名 fixture
    覆寫這一支，並且照樣 depend on `clean_db`。
    """
    return clean_db
