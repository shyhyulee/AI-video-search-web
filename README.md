# AI 影片搜尋

Web 應用：下載或上傳影片後自動分析（場景切分、語音辨識、畫面描述、畫面文字辨識），讓使用者用自然語言描述（人物、動作、物件、教學內容）搜尋影片中的關鍵時刻，取代人工逐格瀏覽。後端 FastAPI，前端 React。

## 功能

- **影片與分析**：貼上 YouTube 網址下載，或上傳本機影片檔案，加入待分析清單後一鍵開始分析（進度即時輪詢顯示）。
- **影片庫**：已分析影片列表（可依名稱／片段數／成本／日期排序與篩選）、自動摘要、縮圖、詳細資訊、快速跳轉搜尋。
- **搜尋結果**：自然語言查詢、結果列表（時間範圍／相似度／融合分數／命中來源）、詳細分數面板、片段播放（跳轉至時間點）、CSV 匯出。
- **對話搜尋**：多輪對話式搜尋，可接續指代「播放第二段」「只看穿紅色衣服的人」等追問。
- **YouTube 搜尋**：用關鍵字搜尋 YouTube，卡片式列出前 12 筆（縮圖／標題／頻道／時長／觀看數），展開卡片可看到網址與說明並一鍵複製。只讀 metadata，不下載影片——要下載分析請到「影片與分析」頁貼網址。

> 桌面版 Tkinter UI 已於 Web 版上線後移除；`docs/07-ui-structure-and-features.md` 保留其設計記錄供參考，`docs/09-web-ui-migration-plan.md` 記錄完整遷移過程。

## 系統需求

- Python ≥ 3.11（開發環境固定用系統 Python，見 `.python-version`）
- [uv](https://docs.astral.sh/uv/)
- Node.js ≥ 18 與 npm（前端建置）
- 系統套件：`ffmpeg`／`ffprobe`（場景抽幀、縮圖、探測本機影片長度用）、`node`（yt-dlp 下載時解 YouTube 簽章挑戰用，跟前端建置共用同一份 Node.js）
- OpenAI API 金鑰（分析與搜尋都需要呼叫 Whisper／GPT-4o-mini／text-embedding-3-small）

## 安裝

```bash
uv sync                       # 後端
cd frontend && npm install    # 前端
```

## 設定

在專案根目錄建立 `.env`（已加入 `.gitignore`，不會進版控）：

```
OPENAI_API_KEY=sk-...
```

## 執行

開發模式需要同時跑後端 API 與前端 dev server（兩個終端機）：

```bash
# 終端機 1：後端 API（http://127.0.0.1:8000）
uv run ai-video-search-web

# 終端機 2：前端（http://127.0.0.1:5173，透過 vite proxy 轉發 /api 給後端）
cd frontend && npm run dev
```

打開 `http://127.0.0.1:5173` 使用。第一次執行會自動在專案根目錄建立 `app.db`（SQLite 資料庫）與 `video/`（下載／上傳的影片檔案），兩者都已加入 `.gitignore`。

## 測試

```bash
# 後端
uv run pytest                  # 一般測試，純邏輯／mock，不呼叫真實 API
uv run pytest -m integration   # 整合測試，呼叫真實 OpenAI API，有極小額費用

# 前端
cd frontend
npx tsc -b --noEmit             # 型別檢查
npx oxlint                      # lint
npm run build                   # production build
```

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
  db/              # SQLite 存取層（videos／segments／ocr_events／search_log／jobs／conversations）
  downloader.py    # YouTube 下載（yt-dlp）
  services/        # Application Service 層：包裝 db／pipeline，供 API 使用
    job_manager.py     #   背景工作序列化、進度持久化、重試、啟動時 reconciliation
    video_service.py   #   影片 CRUD、縮圖、長度探測
    search_service.py  #   薄包裝 pipeline.search.search()
    conversation_service.py  # 對話狀態持久化
    stats_service.py   #   Header 統計
  schemas/         # API 對外 Pydantic 契約
  api/             # FastAPI：main.py + 五個 router（videos／jobs／search／conversations／stats）
  pipeline/        # 分析與搜尋 pipeline（以下列主要模組，其餘見原始碼）
    analyzer.py        #   orchestrator：串起場景切分→ASR→VLM→embedding→索引
    scene_detect.py     #   場景切分（PySceneDetect）
    asr.py               #   語音轉文字（Whisper）＋幻覺字幕過濾
    vlm.py                #   畫面描述＋畫面文字（GPT-4o-mini）
    ocr_service.py        #   本地 OCR 掃描（EasyOCR，補 VLM 漏掉的文字）
    embedding.py           #   文字向量化
    search.py               #   Hybrid（Dense+BM25）+ RRF 融合搜尋
    conversation.py         #   多輪對話 orchestrator
    evaluation.py            #   Golden Set 評分
frontend/          # React + TypeScript + Vite + Tailwind + TanStack Query
  src/api/           #   後端 API client 與型別
  src/components/    #   共用元件（Badge／StatCard／EmptyState...）
  src/pages/         #   四個頁面（VideosPage／LibraryPage／SearchPage／ConversationPage）
tests/             # pytest 測試（單元測試 + integration marker）
  api/               #   FastAPI TestClient 測試
scripts/           # 手動執行的工具腳本（Golden Set 評測）
docs/              # 開發文件、規劃記錄與 Golden Set
```

## 成本與限制

- 每支影片分析花費硬上限 **US$0.30**，只分析 **20 分鐘以內**的影片（超過會被 API 擋下回 422，不會嘗試分析後才中止）。
- 目前只接 OpenAI（Whisper／GPT-4o-mini／`text-embedding-3-small`），供應商邏輯以介面隔離，之後可擴充其他供應商。
- 搜尋每次呼叫都會記錄花費，但目前沒有上限或警示機制。
- 同一時間只會有一支影片在跑分析（Job Manager 顯式序列化，其餘排隊），避免同時打多個 API；YouTube 下載不受此限制。
- 伺服器重新啟動時，任何卡在「執行中」的背景工作會被標記失敗，需要手動重試。

## 深入文件

專案的完整背景、架構、開發歷程與技術決策整理在 [`docs/`](docs/00-overview.md)：

- [`00-overview.md`](docs/00-overview.md) — 專案背景需求、系統現況、資料流、Web UI 遷移進度（建議從這裡開始）
- [`01-development-timeline.md`](docs/01-development-timeline.md) — 依日期彙整的開發歷程
- [`02-technical-decisions.md`](docs/02-technical-decisions.md) — 技術決策的背景、比較與實測數據
- [`03-excluded-approaches.md`](docs/03-excluded-approaches.md) — 已嘗試但放棄的方案
- [`04-testing-and-evaluation.md`](docs/04-testing-and-evaluation.md) — 測試套件、Golden Set、評測 baseline
- [`05-known-limitations-and-open-items.md`](docs/05-known-limitations-and-open-items.md) — 已知限制、待辦、待確認事項
- [`06-conversational-search-flow.md`](docs/06-conversational-search-flow.md) — 對話搜尋設計
- [`07-ui-structure-and-features.md`](docs/07-ui-structure-and-features.md) — 已移除的 Tkinter UI 完整盤點（歷史記錄）
- [`09-web-ui-migration-plan.md`](docs/09-web-ui-migration-plan.md) — Web UI 遷移計畫、架構決策、Job Manager 設計、各 Phase 驗收紀錄

`docs/` 底下其餘檔案是各功能主題的原始規劃文件與逐日開發紀錄，仍會持續被程式碼註解引用，保留原樣不動。
