# Web UI 遷移計畫

> **類型**：執行紀錄｜**狀態**：任務已完成，唯讀
> 分類說明與完整索引見 [`../README.md`](../README.md)。

## 1. 文件目的

專案目前是 Tkinter 桌面應用（五個頁籤：影片與分析／影片庫／搜尋結果／對話搜尋／處理紀錄），要在保留既有 Python pipeline／DB 邏輯不重寫的前提下，新增一版 Web UI（React + FastAPI），過渡期兩者並存。

`../prompts/08-web-ui-migration-design.md` 已有一份參考設計（技術選型、API 草案、頁面設計），但那份文件是在**沒有實際盤點現有程式碼**的情況下寫的，且它自己的第 4 節檔案結構建議（`src/existing_pipeline/`）跟它自己的警語（「`src/ai_video_search_web` 目前實際包含 Tkinter，不要立即重新命名」）互相矛盾。

本文件的目標是依照專案**目前程式與檔案的真實現況**（已用三個 Explore agent + 一個 Plan agent 完整盤點、且逐一親自讀過全部關鍵原始檔驗證行號與事實）重新推導一份可執行的計畫。技術選型大致沿用 `../prompts/08-web-ui-migration-design.md`（React／FastAPI／Polling 這些主流選擇沒有爭議），但架構細節、Job 設計、檔案結構、分期順序都改成基於實測事實推導，多處明確偏離該文件。

**目前狀態**：Phase 0～Phase 4 全部完成。實作細節與跟本文件原規劃的落差見 4.2／4.3／4.4／4.5 節「實作紀錄」。Phase 3 一開始受限於環境缺 Playwright 系統函式庫（`libnspr4.so` 等）無法視覺驗證，使用者事後手動裝好相依套件解鎖後，已補做完整的瀏覽器互動測試（見 4.4 節）。Phase 4 在使用者實測過上傳／YouTube 下載／分析輪詢後執行，過程中發現並記錄了一個真實的已知限制（見 4.5 節「實作紀錄」的「job 追蹤跨頁籤遺失」），使用者知情後選擇先完成 Phase 4 收尾，這個限制留待之後再處理。Tkinter UI（`ui/`／`app.py`／`theme.py`）已移除，專案現在是純 Web 應用。

## 2. 現況關鍵事實（決策依據）

### 2.1 兩種完全不同的「非同步」模式並存

- **Category A**（`pipeline/analyzer.py`、`downloader.py`）：有專屬 `start_analysis(video_id, queue) -> Thread` / `start_download(url, queue) -> Thread` 進入點，背景 thread 透過呼叫端傳入的 `queue.Queue` 持續 put 具名事件（`AnalysisProgress`/`AnalysisResult`/`AnalysisError`、`DownloadProgress`/`DownloadResult`，定義於 `analyzer.py:96-114`、`downloader.py:33-47`）。`analyzer.py` 內部還有二層並行：VLM 批次 `ThreadPoolExecutor`（`VLM_BATCH_SIZE=3`，`analyzer.py:87,374`）、embedding 批次（`_embed_segment_texts`，`analyzer.py:513-528`）、「場景切分+ASR 同時跑」「本地OCR+摘要同時跑」兩組巢狀 thread。
- **Category B**（`pipeline/search.py:179 search()`、`pipeline/conversation.py:52 handle_turn()`）：**完全同步、單次呼叫直接回傳值**，沒有 Queue、沒有進度事件。「非同步化」目前完全外包給 Tkinter UI 層自己包 `threading.Thread`（`ui/search_tab.py`、`ui/conversation_tab.py`）。

**結論**：Job Manager／`jobs` 表只服務 Category A 兩個函式；Category B（search／對話／摘要）走一般同步 REST（FastAPI threadpool），不進 Job 表、不輪詢——秒級呼叫套輪詢只會多引入延遲，沒有 UX 收益。

### 2.2 四個「單一 Tkinter／單一使用者」假設，Web 化會直接失效

1. `start_analysis(video_id)` / `start_download(url)` **對重複呼叫零防呆**（無鎖、無去重）。兩分頁同時觸發同一支影片分析會產生兩條 worker thread，`_write_segments()`（`analyzer.py:531-559`）沒查重，**segments 會重複插入兩份**。
2. `downloader.py:79` 下載檔名只依賴 YouTube 標題（`VIDEO_DIR/%(title)s.%(ext)s`），**無 video_id/job_id 命名空間隔離**，標題撞名會互相覆蓋。
3. `ConversationState`（`conversation.py:36-41`）docstring（7-11 行）明講「本機單人桌面 App，不需要 conversation_id：一個頁籤實例就是一個對話」。**全 codebase 沒有 conversation_id 概念**。好消息：`handle_turn()` 是純函式（`_handle_*` 都建構全新 state，見 85-91/109-115/128-134/155-163 行），且 `ConversationState` 全部欄位是 str/int/float/None/list，**可直接 JSON 序列化**。
4. 兩處 process 級可變全域狀態：`search.py:415 _title_summary_embedding_cache`（重啟清空，不寫回 DB）、`openai_client.py` 的 `get_client()`（`@lru_cache(maxsize=1)` 單例）。多 worker process 部署下會分裂成多份、增加 API 呼叫次數，但功能不會錯。

### 2.3 安全缺口：長度限制只在 UI 層檢查

`MAX_DURATION_SEC=1200`（`analyzer.py:52`）只在 `is_within_duration_limit()`（`analyzer.py:152-153`）定義，**`_analyze_worker()` 本身不檢查**；實際強制執行點只有 `ui/video_tab.py:370,377`。同樣，`find_by_source_url()` 查重也只在 `video_tab.py:202` 被呼叫。**直接打 API 會繞過這兩道防線**——必須在 Phase 2（API 一出現）就補上，不能拖到最後。

### 2.4 資料庫現況

只有 4 張實體表（`videos`／`segments`／`ocr_events`／`search_log`）+ 1 張 FTS5 虛擬表，**沒有 jobs/tasks/progress 表**。`videos.status` 只有 `pending/analyzing/analyzed/failed` 四值（`db/videos.py:10-16`），覆蓋式更新，無法保留失敗歷史。`db/__init__.py:21-24 get_connection()` 每次呼叫各自開新連線，**無 WAL、無 timeout 設定**（預設 5 秒 busy timeout）、無連線池。`analyzer.py` 逐百分比進度（場景切分/ASR/本地OCR，透過 `progress_estimation.run_with_estimated_progress` 用經過時間**反推預估值**）只 put 到記憶體 queue、不寫 DB；只有 VLM 階段（`_run_vlm_phase` 的 `_report_progress`，`analyzer.py:367-372`）會同時寫 DB 又 put queue。

### 2.5 pyproject.toml 決定了檔案結構的邊界

```toml
[project.scripts]
ai-video-search-web = "ai_video_search_web:main"
[build-system]
requires = ["uv_build>=0.12.1,<0.13.0"]
build-backend = "uv_build"
```

沒有 `[tool.uv.build-backend]` 覆寫，`uv_build` 預設只認 `src/<單一 module>`。把 pipeline 搬到 `../prompts/08-web-ui-migration-design.md` 建議的 `src/existing_pipeline/` 要嘛加多模組設定、要嘛動 20+ 檔案的 import path，換不到任何功能，純屬搬遷風險。**FastAPI 相關程式碼應該長在 `src/ai_video_search_web/` 內部**，跟現有 `db/`／`pipeline/`／`ui/` 平行，不新增頂層 `backend/`。`frontend/` 維持該文件建議：獨立 sibling 目錄，自己的 `package.json`，跟 Python packaging 無關。

`pydantic>=2.13.4` 已是既有依賴（`pipeline/intent.py`／`translation.py`／`vlm.py` 用於 LLM structured output），FastAPI 原生用 Pydantic v2，型別風格可沿用，但 API 對外 schema 要跟這些內部私有 LLM-output schema **分開**，不要合併復用。

### 2.6 Provider 抽象層可直接復用

`pipeline/` 對 `ui/`／`tkinter`／`messagebox`／`filedialog` **零 import**（已嚴格 grep 確認），FastAPI service 層可以直接 import `pipeline/*`，不用碰 `ui/`。`asr.py`/`vlm.py`/`embedding.py`/`summary.py`/`translation.py`/`intent.py` 六個模組都用「`client: OpenAI` 當第一參數顯式傳入」風格，測試上直接傳 `MagicMock()`；這個風格天生對應 FastAPI `Depends()`，pipeline 層不需要為了「可測試」而改動。

### 2.7 已明確決策：不做多影片平行分析

`../02-technical-decisions.md:278-280`（Tier 3）評估後**決定不做**「多支影片之間平行分析」（跟「序列處理避免同時打多個 API」的設計衝突）。這個約束今天能成立**純粹是意外繼承**——因為只有一個 Tkinter 視窗、`video_tab._start_next_analysis()` 是「pop 完才排下一支」的迴圈。Web 化後這個約束會直接消失，除非 Job Manager 把它變成顯式機制（見 3.2）。

## 3. 建議架構

### 3.1 檔案結構

```text
src/ai_video_search_web/
├── app.py, theme.py, ui/, db/, pipeline/      # 不動（僅 2 處例外，見下）
├── services/            # 新增：job_manager.py, video_service.py, search_service.py,
│                         #        conversation_service.py, stats_service.py
├── schemas/              # 新增：API 對外 Pydantic 契約（跟 pipeline 內部私有 LLM schema 分開）
└── api/                  # 新增：main.py, videos.py, jobs.py, search.py, conversations.py, stats.py
frontend/                 # 新增：獨立 sibling，自己的 package.json（React+TS+Vite）
tests/
├── test_*.py             # 既有 207 個測試不動
├── test_services_*.py    # Phase 1 新增
└── api/                  # Phase 2 新增，pytest 自動遞迴發現，免改 pyproject
    ├── conftest.py        #   共用 fixture：temp_db／client／make_video()
    └── test_api_*.py      #   注意：命名前綴要跟 tests/ 根目錄不同（例如
                            #   test_api_search.py 而非 test_search.py）——
                            #   tests/ 沒有 __init__.py，pytest 預設 prepend
                            #   import mode 下，同名檔案放在不同子目錄會撞名
                            #   （import file mismatch），實測踩過這個坑。
```

**僅兩處對既有檔案的修改**（其餘 pipeline 檔案零修改）：

1. `downloader.py`：`start_download()`/`_download_worker()` 加可選參數 `dest_dir: Path | None = None`（預設值＝現有 `VIDEO_DIR`，Tkinter 呼叫端零改動），解決「不同 URL、相同標題」的檔名衝突根因（單純加鎖只防得住「同一支影片點兩次」，防不住撞名）。
2. `db/__init__.py`：`get_connection()` 加 WAL + busy_timeout（見 3.2），對 Tkinter 呼叫端完全透明。

`pyproject.toml` 新增依賴 `fastapi`、`uvicorn[standard]`、`python-multipart`（`UploadFile` 需要），新增第二個 `[project.scripts]` 項目（`ai-video-search-web-api`），原有的 Tkinter entry point 不動。

### 3.2 Job Manager 設計

**新表**（延續 `db/videos.py` 的 `create_table`／`_row_to_record` 慣例，不加 CHECK/FK，跟現有 4 張表風格一致）：

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL,                 -- 'download' | 'analysis'
    video_id INTEGER,                       -- analysis: submit 當下就有；download: 完成後才回填
    source_url TEXT,                        -- download job 的 dedup key
    status TEXT NOT NULL DEFAULT 'queued',  -- queued | running | completed | failed（僅四種，理由見下）
    stage TEXT,
    progress_percent INTEGER,               -- 多數階段是 NULL 或「預估值」，不是精確進度（見 2.4）
    progress_message TEXT,
    error_message TEXT,
    cost_usd REAL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_video_id ON jobs(video_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state_json TEXT NOT NULL,               -- json.dumps(dataclasses.asdict(ConversationState))
    total_cost_usd REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

**事件持久化機制**：`JobManager` 起一條 pump thread drain `analyzer.start_analysis()` / `downloader.start_download()` 原本就會產生的 queue，把 `AnalysisProgress`/`Result`/`Error` 事件轉寫成 `jobs` 表的 UPDATE——**不改動 `analyzer.py`/`downloader.py` 任何一行既有 threading/併發邏輯**，只是把「原本會被 Tk widget 讀走的事件」改成「寫進 DB 列」。`downloader.py` 這邊多一步：收到 `DownloadResult` 時呼叫 `db.insert_video()` 並回填 `jobs.video_id`（這個職責從 `video_tab.py` 的 UI callback 移過來）。

**顯式序列化**：`job_type='analysis'` 用 `threading.Semaphore(1)` 保證同時只有 1 個 `running`（把 2.7 節的隱性約束變成顯式機制）；`job_type='download'` 不受限（不呼叫 OpenAI，不消耗 `BUDGET_USD`）；search／對話不進 Job 表，不受限。

**Submit 流程**（以 `submit_analysis(video_id)` 為例）：查 `jobs` 表是否已有該 `video_id` 的 `queued`/`running` 列 → 有則 409；呼叫既有 `analyzer.is_within_duration_limit()` → 不合格 422；insert `jobs(status='queued')`；輪到時呼叫**不動**的 `analyzer.start_analysis()`。

**Retry／Cancel 範圍刻意縮小**：pipeline 完全沒有 checkpoint／取消 token，做「真取消」要把訊號貫穿進每個 phase 函式，超出這次遷移的合理範圍。所以：

- Job 狀態只做 `queued/running/completed/failed` 四種（`../prompts/08-web-ui-migration-design.md` 建議六種含 `retrying`/`cancelled`，本計畫不採用，避免做出假的取消能力）。
- **Retry** = 對失敗 job 呼叫 `db.reset_to_pending()` 後建**全新**一筆 job 重新 submit（舊列保留當歷史）。
- **Cancel** 只支援 `queued` 狀態（直接標記失敗＋「使用者取消」訊息）；`running` 不支援，API 回 409。

**Conversation 狀態**：`conversation_service.send_message(conversation_id, message)` 讀 `state_json` → `json.loads` 還原 → 呼叫**不動**的 `conversation.handle_turn()` → 序列化寫回。成本歸屬用「對話層級彙總」（`conversations.total_cost_usd += turn_result.cost_usd`），不動 `search.py` 簽名加 `conversation_id` 參數逐筆歸屬——零 pipeline 改動，若之後真的需要逐筆歸屬再加。

**Zombie job**：`_analyze_worker()` 一開始就寫 `STATUS_ANALYZING`（`analyzer.py:174`），process 被砍掉會卡在這個狀態。FastAPI startup 加一次 reconciliation：把所有 `status='running'` 的 job 標記失敗（「伺服器重新啟動，任務中斷」），可再用上面的 retry 流程重跑。

**SQLite WAL**：

```python
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn
```

WAL 讓讀者不擋寫者、寫者不擋讀者，對症下藥「多請求同時讀、pump thread 偶爾寫」這個比 Tkinter 更高頻的並發模式。對呼叫端完全透明，不影響既有 207 個測試。

**部署約束（刻意的簡化）**：FastAPI 只跑**單一 worker process**（`uvicorn ... --workers 1`）。這讓 `_title_summary_embedding_cache`／`get_client()` 快取語意跟今天完全相同，不用改一行程式碼；Job Manager 的 dispatcher 也只需要 in-process `Semaphore`，不需要跨 process 協調。之後真的要水平擴展，快取才需要搬進 Redis／DB，現在做是過度工程。

### 3.3 為何不用 Celery + Redis

考慮過，不採用：

1. `analyzer.py` 的進度介面是 `queue.Queue`，硬套 Celery 等於在 worker process 裡重新做一次上面的 pump thread，多繞一層 infra 沒有換到 Celery 原生能力。
2. 併發上限本來就該是 1（2.7 節），`Semaphore(1)` 已經足夠。
3. 專案目前零部署基礎設施，引入 Redis+broker 直接違背 `../prompts/08-web-ui-migration-design.md` 自己「第一版不強制導入微服務」。
4. SQLite 不適合當 Celery broker，會逼著同時換資料庫，違反該文件「先避免同時遷移資料庫」的原則。

真正需要 Celery 的時機是「多支影片真的要平行分析」——但那正是 2.7 節已評估並否決的方向，若此產品決策不變，不需要這套 infra。

同樣考慮過「把 Tkinter 5 處輪詢骨架跟 Job Manager 抽成共用邏輯」——`../02-technical-decisions.md:74-81` 已記錄類似想法評估後不做（5 處其實是三種不同寫法，硬抽共用骨架換到的行數少）。本計畫延續這個判斷，且 Job Manager 的輪詢需要 DB 持久化＋HTTP 語意，跟 Tk 輪詢需要 UI-thread-safe callback 本質不同，Phase 1 明確不把 Tkinter 改成呼叫 Job Manager。

## 4. 分階段實作順序與驗收條件

風險排序原則：既有 207 個測試全程不能壞；`MAX_DURATION_SEC`／`find_by_source_url` 這兩個目前只在 UI 層的防線必須在 Phase 2 就補齊。

### 4.1 Phase 0（本文件，已完成）

盤點＋設計，未改動任何程式碼。

### 4.2 Phase 1 — 抽出 Service 層（只服務 Category B + CRUD，不含 Job Manager）✅ 已完成

新增：`services/video_service.py`（含 `probe_local_duration()`，從 `video_tab.py:39-48` 原樣搬過來）、`search_service.py`、`conversation_service.py`（此階段還不接 `conversations` 表，維持記憶體 state）、`stats_service.py`。

修改：`ui/video_tab.py`／`library_tab.py`／`search_tab.py`／`conversation_tab.py` 改呼叫 service 而非直接呼叫 `db.*`／`pipeline.*`；`_on_download_clicked`／`_on_analyze_clicked` 內部呼叫 `downloader.start_download()`／`analyzer.start_analysis()` 的方式維持原樣，**不**套用 Job Manager。

**驗收**：`uv run pytest` 207 個既有測試全綠（service 層是透傳包裝，行為需位元級相同）；新增 `tests/test_services_*.py`。**已知缺口**：`ui/*_tab.py` 本身目前零自動化測試（`test_widgets.py` 只測 `ui/widgets.py` 格式化函式），pytest 全綠不代表 Tkinter 視窗沒壞，這階段須額外人工跑一次 `uv run ai-video-search-web`，五個頁籤主要操作各點過一輪。

**實作紀錄**：程式碼與上述規劃一致，新增 21 個 service 測試，`uv run pytest` 227 通過（206 舊有 + 21 新增）+ 1 deselected。實作過程中發現規劃時漏列一處呼叫點：`library_tab.py` 的 `_on_regenerate_summary_clicked()` 除了 `_build_row()` 之外還有另一處獨立的 `db.list_segments_for_video()` 呼叫，已一併改成呼叫 `video_service`。**人工驗證待辦**：此開發環境無 GUI 顯示，無法啟動 Tkinter 視窗，五個頁籤的人工點測驗收項目尚未執行，需要你本機驗證。

### 4.3 Phase 2 — FastAPI + Job Manager（API 完整，前端還沒開始）✅ 已完成

新增：`db/jobs.py`、`db/conversations.py`（掛進 `db/__init__.py init_db()`）、`services/job_manager.py`、`schemas/*.py`、`api/main.py`＋五個 router、`tests/api/test_*.py`（FastAPI `TestClient`）。

修改：僅 `db/__init__.py`（WAL）與 `downloader.py`（`dest_dir` 參數）。

**驗收**（安全缺口必須在此階段修復）：

- 既有 207 + Phase 1 新增測試全綠。
- `POST /api/v1/videos/{id}/analyze` 對超長影片回 422（把 `video_tab.py:370,377` 的檢查補進 API）。
- `POST /api/v1/videos/youtube` 對已存在 `source_url` 回 409（把 `video_tab.py:202` 的檢查補進 API）。
- 併發測試：同一 `video_id` 連發兩次 `/analyze` 第二次回 409；兩個不同 `video_id` 連發，第二個停在 `queued` 直到第一個變終態（驗證 Semaphore(1) 真的生效）。
- Startup reconciliation 有測試覆蓋。
- `GET /docs`（Swagger）手動核對每個 endpoint 一次。

**實作紀錄**：

- `uv run pytest` 256 通過（227 + 29 新增 API 測試）+ 1 deselected；上述 5 項驗收條件各自有對應測試，實測皆通過。另外用真實 `uvicorn`（非 TestClient）啟動，確認 `/docs`／`/openapi.json`（18 條路徑）／`/api/v1/stats` 都正常運作，且正確讀到真實 `app.db`（7 支已分析影片、537 個片段）。
- `pyproject.toml` 新增 `fastapi>=0.115`、`uvicorn[standard]>=0.32`、`python-multipart>=0.0.9`（實際解析到 fastapi 0.141.1／starlette 1.6.0／uvicorn 0.52.4），新增 `ai-video-search-web-api` script entry。
- 比原規劃多實作兩個 service 函式（規劃時沒預先想到，實作 API 時才發現需要）：`video_service.generate_thumbnail()`（供 `/videos/{id}/thumbnail`，沿用 `library_tab.py._set_thumbnail()` 的 ffmpeg 邏輯，即時產生不快取，Phase 3 規劃的「分析完成時就產生並保存」還沒做）、`video_service.register_uploaded_video()`（跟 `register_local_video()` 的差別：Web 上傳時磁碟檔名是系統產生的 uuid，跟使用者看到的標題是兩件事，不能沿用 `path.stem` 當標題）。`db.jobs.list_jobs()` 額外支援 `job_type`／`status` 篩選（dispatcher 挑下一個排隊工作要用）。
- **範圍內的取捨**：`../prompts/08-web-ui-migration-design.md` API 設計列的 `GET /api/v1/search/recent`（最近搜尋）**沒有實作**——Tkinter 版本這個功能純粹存在 `SearchResultsTab` 記憶體、`db/search_log.py` 沒有對應的查詢函式，屬於錦上添花功能，不影響任何驗收條件，之後有需要再補。
- **踩到的坑**：FastAPI 0.141.1 的 `app.routes` 在 `include_router()` 之後顯示的是內部 `_IncludedRouter` 物件、不是展開後的個別 endpoint 列表（跟舊版行為不同），直接數 `len(app.routes)` 會誤判成「路由沒掛上去」；正確驗證方式是打 `/openapi.json` 或直接用 `TestClient` 呼叫端點。另外測試 `test_second_analysis_job_waits_for_first_to_finish` 一度因為背景 pump thread 沒等它完全跑完（`mark_job_completed` + 鏈式派發下一個）測試函式就返回，導致 thread 殘留到下一個測試、撞上已經被 `monkeypatch` 換掉的 `db.DB_PATH`（`sqlite3.OperationalError: no such table: jobs`）；修法是讓測試明確 poll 到工作真的變成終態才返回，不能只 `set()` 事件就結束——這是背景執行緒測試常見的坑，記錄下來供之後寫 Phase 3 的非同步測試參考。

### 4.4 Phase 3 — React 前端（風險由低到高）✅ 已完成（四個頁面，含瀏覽器互動實測）

順序：Header 統計 → 影片庫 → 單次搜尋＋播放器 → 影片上傳與分析任務 → 對話搜尋 → 處理紀錄。

- **影片庫**：`重新分析`／`重新產生摘要`是本階段唯一新複雜度，兩者都是既有 Category A/B 操作，沒有新模式。縮圖改成分析完成時就產生並保存到 `video/thumbnails/{video_id}.jpg`（不要每次開詳細資料才跑 ffmpeg）。
- **搜尋＋播放器**：`GET /videos/{id}/stream` 用 Starlette `FileResponse`（內建 Range 支援）；瀏覽器 seek 是這步第一次要驗證的新風險面（桌面 `ffplay` 不會暴露這類問題）。
- **上傳與分析任務**：**本階段風險最高的一步**，同時要做 (a) multipart 上傳進度、(b) `GET /jobs/{id}` 輪詢 UI 兩個新模式；可視情況拆成「先本機上傳」「再 YouTube 下載+分析輪詢」兩個子階段。
- **對話搜尋**：重用第 3 步的 Result Card／Player，只新增訊息串與 `conversation_id` 狀態管理。
- **處理紀錄**：優先序最低。`_QueueLogHandler`＋`deque(maxlen=1000)`（`logs_tab.py`）是純 in-process 狀態，在「單 worker」約束下可以直接暴露 `GET /api/v1/logs` 讀同一份 deque，但這只在單 process 部署下成立，本計畫**明確標記為技術負債、這次不解決**（不是核心使用者流程，投入產出比低）。

**驗收**：`../prompts/08-web-ui-migration-design.md` 第 10 節驗收標準逐項手動驗證（重新整理不遺失任務狀態、CSV 匯出、跳轉播放時間點等）；「送出搜尋看到結果」「上傳並看到分析完成」兩條關鍵路徑至少有 E2E 測試（可用 Playwright）。

**實作紀錄**：

- 技術棧沿用 `../prompts/08-web-ui-migration-design.md`：Vite + React 19 + TypeScript + Tailwind v4（用新版 `@tailwindcss/vite` plugin，CSS-first `@theme` 設定，不需要 `tailwind.config.js`／`postcss.config.js`）+ TanStack Query v5 + `react-router-dom`。**沒有引入 shadcn/ui**——這是刻意的範圍縮減：shadcn/ui 是用 CLI 從遠端 registry 複製元件原始碼進專案的機制，會多一層設定與網路依賴，這一輪的元件複雜度（表格、卡片、表單）用純 Tailwind utility class 就能對齊 `theme.py` 的設計系統（顏色／間距值直接抄過來，見 `frontend/src/index.css` 的 `@theme` 區塊），之後真的需要更複雜元件（Dialog、Combobox 之類）再評估加入，不算違背原技術選型的精神。
- 4 個頁面（`影片與分析`／`影片庫`／`搜尋結果`／`對話搜尋`）全部完成，路由骨架見 `frontend/src/App.tsx`；**「處理紀錄」維持不做**，跟規劃一致。
- 開發模式用 Vite dev server 的 `server.proxy`（`vite.config.ts`）把 `/api/*` 轉給 `127.0.0.1:8000`，前端程式碼一律用相對路徑呼叫 API，瀏覽器端同源、不觸發 CORS——後端 `api/main.py` 的 `CORSMiddleware` 設定變成「非 proxy 場景」（例如以後獨立部署）的保險，不是開發時實際依賴的機制。
- `VideoOut` schema 補了三個規劃時沒想到、但 UI 需要的欄位：`has_transcript`／`has_visual`／`has_ocr`（`schemas/videos.py`、`api/videos.py`），邏輯抄自 `ui/library_tab.py._build_row()`，供影片庫的三個 Badge 使用；這是新層（schemas／api）的自然擴充，不算修改既有檔案的範圍。
- 上傳進度用 `XMLHttpRequest`（不是 `fetch`）——`fetch` 目前沒有原生的上傳進度事件；下載／分析進度沿用既有 `useJobPolling`／`useJobsPolling`（`frontend/src/lib/useJobPolling.ts`，基於 TanStack Query 的 `refetchInterval`，終態自動停止輪詢）。
- **驗證方式（分兩階段）**：這個開發環境一開始沒有 Playwright headless Chromium 需要的系統共用函式庫（`libnspr4.so` 等），`sudo apt-get install` 需要互動式密碼，環境本身裝不了；先用三層驗證頂替：(1) `tsc -b --noEmit` 型別檢查全過；(2) `npm run build` production build 成功（85 modules，299KB／92KB gzip）；(3) `oxlint` 零警告（含修掉兩處 React 反模式：在 render body 直接呼叫 `queryClient.invalidateQueries()`，改寫成 `useEffect`）；(4) 透過 Vite proxy 對真實 FastAPI／`app.db` 做端到端 curl 測試。使用者事後在自己的終端機用 `! sudo apt-get install ...` 補裝相依套件解鎖後，補做了完整的 Playwright 瀏覽器互動測試：四個頁面截圖、影片庫點列表看詳細面板（縮圖／Badge／摘要都正確渲染）、影片庫排序與篩選按鈕、搜尋「獅子」拿到 6 個正確排序結果並點結果驗證 HTML5 Video 正確 seek 到片段起始時間（畫面確實跳到獅子出現的那一幀）、對話搜尋送出訊息拿到正確回覆與結果、對話結果點擊播放同樣正確 seek。全程 `page.on('console'/'pageerror')` 監聽零錯誤。

### 4.5 Phase 4 — 切換與清理 ✅ 已完成

兩邊穩定運行一段時間、功能對等確認後才移除 `ui/`／`app.py`／`theme.py`；才處理 `ai_video_search_web` 命名／`[project.scripts]` 收斂；同步更新 `../00-overview.md`（目前仍只寫「四個頁籤」，未提對話搜尋，`07-ui-structure-and-features.md` 已標注此落差待確認）。

**實作紀錄**：

- **執行前的功能對等確認**：使用者實際測試了上傳／YouTube 下載／分析輪詢（4.4 節列的「沒做到」項目），過程中發現一個真實的已知限制——**分析中途切換頁籤，該支影片的追蹤狀態會遺失**：job 進度是每個頁面元件自己的 React 區域狀態（`useState`），不是跨頁籤持續存在的全域狀態，切走再切回來不會恢復。已分兩種情況記錄：(1) 工作還在排隊中就切頁 → 回來後恢復顯示「等待分析」，看起來像沒送出過；(2) 工作已經開始跑（DB 狀態變成 `analyzing`）才切頁 → 該影片從「待分析影片」清單消失（因為 `list_pending_videos()` 只查 `status='pending'`），要等分析完成、手動切去「影片庫」才看得到；Header 統計卡也不會自動更新，因為觸發刷新的 `useEffect` 綁在已經卸載的頁面元件上。**根本原因是分析本身在後端持續執行、不受影響，只是前端沒有一個跨頁籤持續存在的追蹤機制**（例如 Header 常駐一個「N 個工作進行中」指示器），這是 Phase 3 的已知架構缺口，不是 Phase 4 要解決的範圍。使用者知情後決定接受這個缺口、先完成 Phase 4，之後有需要再補（建議修法：讓「待分析影片」／「影片庫」兩個列表查詢各自加上背景輪詢，不用追蹤特定 job id，單純定期反映資料庫當下狀態）。
- **實際刪除／改動的檔案**：`git rm -r` 整個 `src/ai_video_search_web/ui/`（8 個模組）、`app.py`、`theme.py`、`tests/test_widgets.py`（測 `ui/widgets.py`，隨其一起移除）。刪除前用 grep 確認 `pipeline/`／`db/`／`services/`／`schemas/`／`api/` 沒有任何檔案 import `ui/`／`app.py`／`theme.py`——這條依賴邊界在 Phase 1-3 全程維持乾淨，刪除本身沒有波及其他模組。
- **進入點收斂**：`src/ai_video_search_web/__init__.py` 的 `main()` 從 `App().mainloop()` 改成呼叫 `api.main.run()`；`pyproject.toml` 的 `[project.scripts]` 從兩個進入點（`ai-video-search-web`／`ai-video-search-web-api`）收斂成一個：`ai-video-search-web` 現在直接啟動 Web API。`[tool.uv] python-preference = "only-system"` 的**設定值維持不變**（改動它有風險、沒有已知效益），但註解改成如實反映「原本因為 Tkinter／Tk CJK 字型問題而設，現在理由已經不成立，純粹維持不動避免無謂變動」，不再誤導成「還需要 Tkinter」。
- **清掉兩處死碼**：`video_service.register_local_video()`（Phase 1 為 Tkinter「選擇本機影片」寫的，title 直接用 `path.stem`）與 `conversation_service.send_message(state, message)`（Phase 1 為 Tkinter 對話頁籤寫的純記憶體介面）——grep 確認兩者的唯一呼叫端都在剛刪除的 `ui/` 內，Web API 分別用 `register_uploaded_video()`／`send_message_by_id()` 取代。對應的舊測試（`test_services_video.py`／`test_services_conversation.py`）沒有直接刪除，改寫成測真正還在用的函式，`test_services_conversation.py` 額外補了 `start_conversation`／`get_conversation_state`／`send_message_by_id` 對 DB 讀寫的直接單元測試（原本只在 `tests/api/test_api_conversations.py` 間接測到）。
- **../README.md 全面改寫**：定位從「Tkinter 桌面應用」改成「Web 應用」；系統需求移除 `ffplay`（HTML5 Video 取代）、加入 Node.js／npm；執行方式改成「兩個終端機分別跑後端＋前端」；專案結構圖換成 `services/`／`schemas/`／`api/`／`frontend/`。順手修正一個實作前就存在的既有 bug：「深入文件」區塊的連結全部指向不存在的 `docs/organize-docs/` 路徑（實際文件都直接放在 `docs/` 下），已改成正確路徑，並補上 06／07／09 三份新文件的連結。
- **驗證**：`uv run pytest` 255 通過（256 − 4，對應被刪除的 `test_widgets.py` 4 個測試，其餘增減互相抵銷）+ 1 deselected；`uv run ai-video-search-web`（新的單一進入點）實測能正確啟動 FastAPI／uvicorn，`/api/v1/stats`／`/docs` 都正常回應，讀到真實 `app.db`（使用者測試期間已把已分析影片數從 7 支增加到 8 支、片段數 537→649，證實 Phase 3 的上傳／下載／分析流程在真實使用中確實可用）。

## 5. 風險與相容性

- **SQLite 並發**：已用 WAL + busy_timeout=30s + 單 worker process 約束處理（見 3.2）。殘餘風險：WAL 在網路檔案系統上可能不可靠，目前 WSL2 環境下 `app.db` 留在 Linux 端檔案系統沒問題，之後若搬到網路磁碟要重新評估。
- **成本追蹤缺口被放大**：`../05-known-limitations-and-open-items.md` 已記錄「搜尋無上限」（`search_log` 沒有警示機制）與「VLM 無斷路器」兩個缺口。桌面版靠「單一使用者、有人盯著看」隱性防線，Web 化後這道防線消失。建議（非阻斷，Phase 2/3 內可做）：`search_service`／`conversation_service` 加簡單的每日累計費用檢查（`SELECT SUM(cost_usd) FROM search_log WHERE date(created_at)=date('now')` 超門檻回 429），順便補上待辦「Header 搜尋累計成本卡」。VLM 斷路器維持不修（超出這次遷移的合理範圍），僅記錄為風險。
- **Tkinter／Web 並存測試策略**：全程只有 `uv run pytest` 一個指令，Phase 1-3 新測試都加進同一個 `tests/`（含 `tests/api/`，pytest 自動遞迴發現）。既有 207 個測試持續是 pipeline/db 層的唯一安全網；新增的 `tests/api/` 保護 Job Manager／schema／endpoint；兩者不重疊不取代。`ui/*_tab.py` 缺乏自動化測試是既有現況（非本次新增缺口），但 Phase 1 影響面最大，必須靠人工跑過 Tkinter 視窗補這個洞。

## 6. 決策速查表

| 決策點 | 採用方案 | 主因 |
|---|---|---|
| 任務佇列 infra | in-process threading + `jobs` 表 | 併發上限本來就該是 1（見 2.7）；Celery/Redis 維運成本遠高於實際需求 |
| Category B 非同步包裝 | FastAPI threadpool，不進 `jobs` 表 | 秒級同步呼叫套輪詢只會多引入延遲，沒有 UX 收益 |
| Tkinter 輪詢骨架 | 維持現狀，不與 Job Manager 共用 | `../02-technical-decisions.md` 的「已排除方案」 已評估類似想法並判定不值得；兩者底層需求本質不同 |
| Conversation 狀態 | 伺服器端 `conversations` 表 | 前端 round-trip 違反「重新整理不遺失狀態」驗收標準；缺乏成本稽核軌跡 |
| 對話成本歸屬 | 對話層級彙總 | 零 pipeline 簽名改動、風險最低 |
| 下載檔名衝突 | 修改 `downloader.py` 加 `dest_dir` 參數 | 單純加鎖解決不了「不同 URL、相同標題」的根本衝突 |
| 專案結構 | FastAPI 程式碼長在 `src/ai_video_search_web/` 內 | `uv_build` 只認 `src/<單一 module>`；參考文件自己也警告不要立即搬遷/改名 |
| Job 狀態集合 | queued/running/completed/failed 四種 | pipeline 無 checkpoint／取消 token，六種會做出假的取消能力 |

## 7. 關鍵檔案索引

- `src/ai_video_search_web/pipeline/analyzer.py` — Category A 核心：`start_analysis`/`_analyze_worker`（156/162 行）、三個事件 dataclass（96-114 行）、`MAX_DURATION_SEC`（52 行）、`BUDGET_USD`（51 行）。Job Manager 的 pump thread 直接消費這裡的 queue 事件，零修改。
- `src/ai_video_search_web/downloader.py` — Category A 另一半，本計畫唯二建議修改的 pipeline 檔案之一（加 `dest_dir` 參數，50/57/79 行）。
- `src/ai_video_search_web/pipeline/search.py`、`pipeline/conversation.py` — Category B 核心，`search()`（179 行）、`handle_turn()`（52 行）、`ConversationState`（36-41 行），零修改直接復用。
- `src/ai_video_search_web/db/__init__.py` — `get_connection()`（21-24 行），本計畫唯二建議修改的既有檔案之二（加 WAL/timeout）；新增 `db/jobs.py`／`db/conversations.py` 要掛進 `init_db()`（86-94 行）。
- `pyproject.toml` — 確認 `uv_build` 單模組慣例與 `[project.scripts]` 綁定，決定新 API 程式碼必須長在 `src/ai_video_search_web/` 內。
- `src/ai_video_search_web/ui/video_tab.py` — 三處「目前只在 UI 層、必須搬進 API 層」的具體位置：`MAX_DURATION_SEC` 檢查（370/377 行）、`find_by_source_url` 檢查（202 行）、`_probe_duration_sec`（39-48 行，Phase 1 原樣搬進 `video_service`）。

## 8. 驗證方式

- **Phase 1**：`uv run pytest`（207 既有 + 新增 service 測試全綠）＋人工跑 `uv run ai-video-search-web` 點過五個頁籤主要操作。
- **Phase 2**：`uv run pytest`（含 `tests/api/`）全綠；`uv run uvicorn ai_video_search_web.api.main:app` 啟動後用 `GET /docs` 手動核對每個 endpoint；針對 422/409/併發序列化三個安全缺口各寫一個明確測試並確認會失敗（改動前）／通過（改動後）。
- **Phase 3**：`cd frontend && npm run dev` 對照 FastAPI dev server，手動走過 `../prompts/08-web-ui-migration-design.md` 第 10 節驗收標準逐項；至少「搜尋」「上傳分析」兩條路徑跑 Playwright E2E。**實測結果**：補裝系統相依套件後，已用 Playwright 完成「搜尋」「對話搜尋」「影片庫排序／篩選／詳細面板」「影片播放 seek」的互動驗證，零 JS 錯誤，見 4.4 節「實作紀錄」。「上傳」「YouTube 下載＋分析輪詢」因需要真的觸發付費 API／長時間 job 流程，這次沒有跑 E2E，只驗證到程式碼與型別層級，是還沒補的驗收缺口，見第 9 節。
- **全程**：兩邊（Tkinter／Web）功能對等前，`uv run pytest` 必須維持全綠，不允許為了 Web 版而修改或刪除既有測試斷言。

## 9. Phase 3 待辦與已知限制

- ~~上傳／YouTube 下載／分析輪詢沒有跑過 E2E~~ **已由使用者實測完成**（Phase 4 執行前），過程中發現下面這項限制。
- **分析中途切換頁籤，該支影片的 job 追蹤狀態會遺失**（Phase 3 已知架構缺口，Phase 4 沒有處理）→ **2026-08-26 應已解決、待實測確認**：`App.tsx` 改用 keep-alive（造訪過的頁籤留在 DOM 裡不卸載，只是隱藏），下面描述的根因「元件卸載導致區域狀態歸零」已經不存在，輪詢在隱藏的頁面也持續進行，Header 統計卡的刷新 `useEffect` 不再綁在被卸載的元件上。做法與驗證見 `docs/11` §8.3；**但沒有實跑一輪真實分析驗證過**，所以先標記為「應已解決」而不是直接劃掉。以下保留原始問題描述：job 進度是「影片與分析」頁面元件自己的區域狀態，不是跨頁籤持續存在的全域狀態。工作還在排隊中就切頁 → 回來後恢復顯示「等待分析」；工作已經開始跑才切頁 → 該影片從「待分析影片」清單消失，要等分析完成、手動切去「影片庫」才看得到；Header 統計卡也不會自動更新。**分析本身在後端持續進行、不受影響**，純粹是前端顯示遺失同步。建議修法：讓「待分析影片」／「影片庫」兩個列表查詢各自加上背景輪詢（例如每 3 秒），不用追蹤特定 job id，單純定期反映資料庫當下狀態；更完整的修法是做一個常駐 Header 的全域工作指示器。詳見 4.5 節「實作紀錄」。
- **`GET /search/recent`（最近搜尋）沒有前端功能**：跟 4.3 節記錄的後端缺口一致，這次沒有補。
- **對話搜尋頁面沒有「指代上一輪結果」的特別 UI 提示**：`pipeline/conversation.py` 的 `select_result` 意圖（例如使用者說「播放第二段」）後端邏輯已經支援（Phase 2 直接復用，零修改），但前端沒有額外標示「目前在指代哪一輪」，使用者體驗上可能不夠明確，之後可以加強。
- **上傳／下載併發限制只在 UI 層用 disable 按鈕做**：YouTube 下載按鈕在下載中會 disable（對齊 Tkinter 行為），但後端 `submit_download()` 本身不限制併發下載數（跟 Job Manager 設計一致，見 3.2 節）；如果使用者用兩個分頁同時操作，後端仍會分別處理，屬於已知、刻意接受的行為，不是這次要修的缺口。
- **前端沒有 loading skeleton／樂觀更新**：目前資料載入中就是空白或顯示上一次的快取資料（TanStack Query 預設行為），沒有額外做 loading 骨架屏；影響體驗但不影響正確性，之後有餘力再補。
