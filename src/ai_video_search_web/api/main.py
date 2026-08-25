"""FastAPI 應用程式進入點：組裝路由、CORS、統一錯誤處理，以及伺服器啟動時
的 job reconciliation（見 docs/09-web-ui-migration-plan.md 3.2 節「Zombie
job」）。跟 app.py（Tkinter 進入點）並存，互不依賴；共用 db／pipeline／
services，見計畫文件整體架構。

部署約束（刻意的簡化，見計畫文件 3.2 節）：只跑單一 worker process。這讓
pipeline/search.py 的 _title_summary_embedding_cache、
pipeline/openai_client.py 的 get_client() 單例快取語意跟 Tkinter 完全相同，
Job Manager 的序列化 dispatcher 也只需要 in-process 鎖，不需要跨 process
協調。之後真的要水平擴展才需要重新設計這幾處。
"""
from __future__ import annotations

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


@asynccontextmanager
async def _lifespan(_app: FastAPI):
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
