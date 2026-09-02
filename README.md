# AI 影片搜尋

Web 應用：從 YouTube 搜尋並下載影片後自動分析（場景切分、語音辨識、畫面描述、畫面文字辨識），讓使用者用自然語言描述（人物、動作、物件、教學內容）搜尋影片中的關鍵時刻，取代人工逐格瀏覽。後端 FastAPI，前端 React。

## 功能

- **新增影片**：用關鍵字搜尋 YouTube，卡片式列出前 40 筆（縮圖／標題／頻道／時長／觀看數）。卡片上可直接「播放」預覽（頁內內嵌播放器），或按「加入待分析」把影片下載進來、排進「影片與分析」頁的待分析清單；展開卡片可看到網址與說明並一鍵複製。搜尋本身只讀 metadata，只有按下「加入待分析」才會真的下載影片；**分析一律在「影片與分析」頁勾選後送出，不在這頁觸發**。
- **影片分析**：待分析影片清單，勾選後開始分析（進度即時輪詢顯示）或移除。**這是全站唯一會觸發分析的地方**；影片本身一律從「YouTube 搜尋」頁加入，這頁沒有新增影片的入口。
- **影片庫**：已分析影片列表（可依名稱／片段數／成本／日期排序與篩選），詳細面板顯示摘要與整理出來的文件（同一段捲動區，摘要在上）。**設定搜尋範圍的地方**：每列可勾選，底部「在選取影片內搜尋」把那一批影片當範圍跳到「搜尋影片」頁；單支影片的「在此影片內搜尋」是「勾一支」的捷徑，走同一條路徑。
- **整理成文件**：在影片庫選一支影片按「整理成文件」，把整支影片的字幕／畫面描述／畫面文字整理成一份有章節、有步驟、每步帶時間戳的結構化文件。**類型由系統依內容自己判斷**：流程 SOP（工廠產線）、教學步驟（烹飪、DIY）、課堂筆記（課程講解），或在影片本來就沒有流程可整理時（球賽、排行榜）退成內容紀錄，不會硬掰。文件裡另有「影片未涵蓋的部分」，標出素材沒交代、要自己補的地方。**同一次呼叫也會更新影片摘要**（文件的概述一稿兩用），所以摘要沒有獨立的按鈕。每份約 US$0.0004～0.003、數秒完成，結果存在影片上，重新整理會覆蓋。
- **片段搜尋**：自然語言查詢、結果列表（時間範圍／相似度／融合分數／命中來源）、詳細分數面板、片段播放（跳轉至時間點）。**全站唯一能輸入自由文字搜尋的地方**（路由仍是 `/search`）。上方以可移除的 chips 顯示目前搜尋範圍；改變範圍不會自動重搜，跟改關鍵字一樣要再按一次「搜尋」。
- **AI對話**：多輪對話式搜尋，可接續指代「播放第二段」「只看穿紅色衣服的人」等追問。跟「片段搜尋」頁**共用同一份搜尋範圍**；範圍是硬邊界，對話裡的自然語言只能在其中再收窄，收窄了會在狀態列標示實際搜了哪幾支。

> 頁籤之間切換不會清空狀態：搜尋關鍵字與結果、搜尋範圍、展開中的卡片、對話記錄、進行中的分析進度都會保留（切走的頁籤留在 DOM 裡不卸載，只是隱藏，並會自動暫停背景播放中的影片）。

> 桌面版 Tkinter UI 已於 Web 版上線後移除；`docs/07-ui-structure-and-features.md` 保留其設計記錄供參考，`docs/09-web-ui-migration-plan.md` 記錄完整遷移過程。

## 系統需求

- Python ≥ 3.11（開發環境固定用系統 Python，見 `.python-version`）
- [uv](https://docs.astral.sh/uv/)
- Node.js ≥ 18 與 npm（前端建置）
- 系統套件：`ffmpeg`／`ffprobe`（場景抽幀、縮圖、探測本機影片長度用）、`node`（yt-dlp 下載時解 YouTube 簽章挑戰用，跟前端建置共用同一份 Node.js）
- Docker（跑 PostgreSQL；見 `docker-compose.yml`）
- OpenAI API 金鑰（分析與搜尋都需要呼叫 Whisper／GPT-4o-mini／text-embedding-3-small）

## 安裝

```bash
uv sync                       # 後端
cd frontend && npm install    # 前端
```

## 設定

在專案根目錄建立 `.env`（已加入 `.gitignore`，不會進版控）；可以直接複製 `.env.example`：

```
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://avs:avs_local_dev@localhost:5433/avs
```

`DATABASE_URL` 不設也能跑——`db/__init__.py` 的預設值就是上面那一行，跟 `docker-compose.yml` 對齊。

## 執行

先把資料庫跑起來（只要做一次，容器之後會自己隨 Docker 啟動）：

```bash
docker compose up -d          # PostgreSQL 17 + pgvector，對外 port 5433
```

再同時跑後端 API 與前端 dev server（兩個終端機）：

```bash
# 終端機 1：後端 API（http://127.0.0.1:8000）
uv run ai-video-search-web

# 終端機 2：前端（http://127.0.0.1:5173，透過 vite proxy 轉發 /api 給後端）
cd frontend && npm run dev
```

打開 `http://127.0.0.1:5173` 使用。後端啟動時會自動建立資料表與索引（`init_db()` 是冪等的，
每次啟動都會跑）；下載的影片檔放在專案根目錄的 `video/`，已加入 `.gitignore`。

> 第一次啟動、或遇到 `docker: command not found`／`address already in use` 之類的卡點，
> 詳細的前置設定、驗證指令與排查對照見 [`docs/15-local-startup-guide.md`](docs/15-local-startup-guide.md)。

> port 用 5433 而不是預設的 5432，是為了避開機器上可能另外裝的 PostgreSQL。
> 資料存在 Docker named volume `avs_pgdata`，容器砍掉重建資料還在。

## 測試

後端測試需要 PostgreSQL 在跑（`docker compose up -d`）。測試會自動建立並使用一個獨立的
`avs_test` 資料庫，每個測試前清空，**不會碰到正式資料庫**——`tests/conftest.py` 會檢查
目標資料庫名稱以 `_test` 結尾才動手。

```bash
# 後端
uv run pytest                  # 一般測試，純邏輯／mock，不呼叫真實 API
uv run pytest -m integration   # 整合測試，呼叫真實 OpenAI API，有極小額費用

# 前端
cd frontend
npx tsc -b --noEmit             # 型別檢查（含 e2e/ 與 playwright.config.ts）
npm run lint                    # oxlint ＋ query key 字面值檢查（見下方）
npm run build                   # production build
npm run test:e2e                # e2e smoke（見下方）
```

`npm run lint` 除了 oxlint，還會跑 `scripts/check-query-keys.mjs`：react-query 的
query key 字面值只准出現在 `src/lib/queryKeys.ts`。這條檢查存在是因為 key 打錯
**不會報錯也不會壞畫面**——換一個 key 照樣呼叫同一個 queryFn，壞掉的只有「誰跟
誰共用快取」與「invalidate 打得到誰」，而那種分岔連 e2e 都看不出來（只會多打一次
API）。只能從結構上禁止。

### 前端 e2e smoke

`npm run test:e2e` 會自己把測試資料庫填成固定的四支假影片、另外起一個後端
（port 8100）與 Vite（port 5273），走過五個頁籤驗證頁面掛得起來、資料載得進來、
互動有反應。port 刻意避開日常開發用的 8000／5173，你手邊的 dev server 開著也能跑。

第一次執行前要裝瀏覽器（只需一次，不進版控）：

```bash
cd frontend && npx playwright install chromium
```

兩件它**刻意不做**的事，見 `frontend/playwright.config.ts`：

- **不碰任何會花錢的路徑**——開始分析、整理成文件、對話搜尋送出、語意搜尋都會呼叫
  OpenAI。唯一會改資料的是「移除影片」，那是全站唯一不花錢的 mutation，留著是因為
  它是驗證 react-query invalidation 有沒有接對的唯一入口。
- **不連正式資料庫**——資料由 `scripts/seed_smoke_db.py` 填進 `avs_test`，
  跟 pytest 一樣有「名稱必須以 `_test` 結尾」的防護。

## Golden Set 評測

用固定的 17 題查詢集量化搜尋品質（Recall@K／MRR／nDCG@K／Timestamp IoU／No-answer F1）：

```bash
uv run python scripts/run_golden_set_eval.py
```

會呼叫真實 OpenAI API（費用是分毫等級），並把結果存成 `docs/eval-runs/<timestamp>.json`。

## 專案結構

```text
src/ai_video_search_web/
  __init__.py      # 套件進入點：main() 啟動 FastAPI（uvicorn）
  db/              # PostgreSQL 存取層（videos／segments／ocr_events／search_log／jobs／conversations）
  downloader.py    # YouTube 下載（yt-dlp）
  services/        # Application Service 層：包裝 db／pipeline，供 API 使用
    job_manager.py     #   背景工作序列化、進度持久化、重試、啟動時 reconciliation
    video_service.py   #   影片 CRUD、縮圖、長度探測
    search_service.py  #   薄包裝 pipeline.search.search()
    conversation_service.py  # 對話狀態持久化
    stats_service.py   #   Header 統計
    errors.py          #   services 層對外丟出的例外型別（API 層對映成 HTTP 狀態碼）
  schemas/         # API 對外 Pydantic 契約
  api/             # FastAPI：main.py + 六個 router（videos／jobs／search／conversations／stats／youtube）
  pipeline/        # 分析與搜尋 pipeline（以下列主要模組，其餘見原始碼）
    analyzer.py        #   orchestrator：串起場景切分→ASR→VLM→embedding→索引
    scene_detect.py     #   場景切分（PySceneDetect）
    asr.py               #   語音轉文字（Whisper）＋幻覺字幕過濾
    vlm.py                #   畫面描述＋畫面文字（GPT-4o-mini）
    ocr_service.py        #   本地 OCR 掃描（EasyOCR，補 VLM 漏掉的文字）
    embedding.py           #   文字向量化
    media.py                #   ffmpeg／ffprobe 呼叫與暫存檔，五個呼叫端共用（含 timeout）
    segment_material.py     #   把片段攤成餵給 LLM 的逐行素材，摘要與文件共用
    search/                 #   Hybrid（Dense+BM25）+ RRF 融合搜尋，一個模組一種責任
      query/sparse/dense/fusion/results/service
    conversation.py         #   多輪對話 orchestrator
    summary.py               #   影片摘要（100～200 字純文字）
    document.py              #   整理成結構化文件（SOP／教學步驟／課堂筆記／內容紀錄）
    evaluation.py            #   Golden Set 評分
frontend/          # React + TypeScript + Vite + Tailwind + TanStack Query
  src/api/           #   後端 API client 與型別
  src/components/    #   共用元件（Badge／StatCard／EmptyState...）
    VideoDetailPanel.tsx      #     影片庫右側：標題、三顆操作鈕、摘要與文件
    VideoWatchView.tsx        #     觀看模式：左播放器、右摘要與文件（點文件時間戳進入）
    VideoSummaryAndDocument.tsx #   上面兩者共用的「摘要＋文件」
  src/pages/         #   五個頁面（YoutubeSearchPage／VideosPage／LibraryPage／SearchPage／ConversationPage）
  src/lib/           #   共用邏輯：格式化、主題分類，以及下面四個跟背景工作有關的
    queryKeys.ts       #     react-query 的 query key 唯一來源（有 lint 檢查擋著手打字面值）
    jobStatus.ts       #     isTerminal()／isActive()
    useJobSettlement.ts #     每個工作到終態時收尾剛好一次
    useAnalysisQueue.ts #     「影片分析」頁的資料層：待分析清單＋跑在上面的工作
  e2e/               #   Playwright smoke（見上方「前端 e2e smoke」）
  scripts/           #   check-query-keys.mjs，掛在 npm run lint 上
tests/             # pytest 測試（單元測試 + integration marker）
  api/               #   FastAPI TestClient 測試
scripts/           # 手動執行的工具腳本
  run_golden_set_eval.py   #   Golden Set 評測
  seed_smoke_db.py         #   把測試資料庫填成固定假資料，供前端 e2e 使用
  migrate_sqlite_to_pg.py  #   一次性：把舊的 app.db 搬進 PostgreSQL（見 docs/14）
docs/              # 開發文件、規劃記錄與 Golden Set
  refactor-board.html      #   歷次重構的任務看板（目前記到第四輪）
```

## 成本與限制

- 每支影片分析花費硬上限 **US$0.80**，只分析 **1 小時以內**的影片（超過會被 API 擋下回 422，不會嘗試分析後才中止）。長度限制擋的是「分析」不是「下載」——加入待分析時不檢查長度。注意兩者可能衝突：長影片可能先撞到 US$0.80 的預算上限而變成部分完成（前面的片段仍可搜尋，後半段沒有索引）。
- 目前只接 OpenAI（Whisper／GPT-4o-mini／`text-embedding-3-small`），供應商邏輯以介面隔離，之後可擴充其他供應商。
- 搜尋每次呼叫都會記錄花費，但目前沒有上限或警示機制。
- 「整理成文件」每份 US$0.0004～0.003（實測 5／33／65 個片段的三支影片），跟摘要一樣累加進該支影片的 `cost_usd`，**沒有獨立欄位**，所以看不出一支影片的成本裡有多少是文件整理。文件品質沒有量化評測方式（搜尋有 golden set，這個只能人工看），已知限制見 [`docs/05`](docs/05-known-limitations-and-open-items.md)。
- 同一時間只會有一支影片在跑分析（Job Manager 顯式序列化，其餘排隊），避免同時打多個 API；YouTube 下載不受此限制。
- 伺服器重新啟動時，任何卡在「執行中」的背景工作會被標記失敗，需要手動重試。

## 深入文件

完整背景、架構、開發歷程與技術決策都在 [`docs/`](docs/README.md)。那裡的文件分成三種性質
（**現況參考**／**執行紀錄**／**原始需求 prompt**），讀之前建議先看
**[`docs/README.md`](docs/README.md)** 的分類索引，避免把已結束任務的計畫當成系統現況。

最常用的幾份：

- [`00-overview.md`](docs/00-overview.md) — 專案背景需求、技術棧、模組分層、資料流、成本與限制（建議從這裡開始）
- [`02-technical-decisions.md`](docs/02-technical-decisions.md) — 每個技術決策的背景、比較與實測數據
- [`05-known-limitations-and-open-items.md`](docs/05-known-limitations-and-open-items.md) — 已知限制、待辦、待確認事項
- [`12-search-query-logic.md`](docs/12-search-query-logic.md) — 一次搜尋的完整處理順序、多關鍵字／複合搜尋的實際行為
- [`15-local-startup-guide.md`](docs/15-local-startup-guide.md) — 本機啟動完整步驟、驗證指令、卡點排查、用 pgAdmin 看資料
