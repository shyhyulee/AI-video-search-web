"""FastAPI 應用程式進入點：組裝路由、CORS、統一錯誤處理，以及伺服器啟動時
的 job reconciliation（見 docs/09-web-ui-migration-plan.md 3.2 節「Zombie
job」）與 logging 設定。

部署約束（刻意的簡化，見計畫文件 3.2 節）：只跑單一 worker process。這讓
pipeline/search/dense.py 的 _title_summary_embedding_cache 與
pipeline/openai_client.py 的 get_client() 這兩個 process 級快取才有意義，
Job Manager 的序列化 dispatcher 也只需要 in-process 鎖，不需要跨 process
協調。之後真的要水平擴展才需要重新設計這幾處。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .. import db
from ..services import job_manager
from .conversations import router as conversations_router
from .errors import install_exception_handlers
from .jobs import router as jobs_router
from .search import router as search_router
from .stats import router as stats_router
from .videos import router as videos_router
from .youtube import router as youtube_router


_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"


def _configure_logging() -> None:
    """設定應用程式自己的 logger 輸出。

    在這之前全專案沒有任何 logging 設定，所有 `logger.warning()`／`logger.error()`
    都只能靠 Python 的 lastResort handler 印出來——沒有時間、沒有模組名稱、
    也看不到 INFO 級別的訊息（例如本地 OCR 提前結束的提示）。

    放在 lifespan 而不是 module import：這樣「被 import」不會有副作用（測試
    與 scripts/ 匯入這個模組時不會被改掉全域 logging 狀態），而不管是
    `uv run ai-video-search-web` 還是直接 `uvicorn ...:app` 都會經過 lifespan。
    uvicorn 自己的設定只動 `uvicorn.*` 那幾個 logger，不碰 root，兩者不衝突；
    basicConfig 在 root 已經有 handler 時（例如 pytest）會自動不動作。
    """
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _configure_logging()
    db.init_db()
    job_manager.reconcile_stale_jobs()
    yield


app = FastAPI(title="AI 影片搜尋 API", version="0.1.0", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite 預設開發埠
    allow_methods=["*"],
    allow_headers=["*"],
)

install_exception_handlers(app)

app.include_router(stats_router, prefix="/api/v1")
app.include_router(videos_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(search_router, prefix="/api/v1")
app.include_router(conversations_router, prefix="/api/v1")
app.include_router(youtube_router, prefix="/api/v1")


def run() -> None:
    """`ai-video-search-web-api` script entry point（見 pyproject.toml）。"""
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, workers=1)
