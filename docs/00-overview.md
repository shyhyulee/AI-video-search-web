# AI 影片搜尋 — 專案總覽

> **類型**：現況參考｜**狀態**：維護中，跟著程式碼更新
> 分類說明與完整索引見 [`README.md`](README.md)。

## 1. 文件目的

這份文件是專案的**總覽層**：系統現在長什麼樣、資料怎麼流、成本與限制在哪裡。想知道「這個資料夾其他文件各自負責什麼」請看 [`README.md`](README.md)，那裡有完整的分類索引。

其餘文件依性質分成三類，`README.md` 有逐份說明：**現況參考**（會跟著程式碼持續維護）、**執行紀錄**（任務已結束，唯讀）、**原始需求 prompt**（使用者當初交付的規格原文，唯讀）。

## 2. 背景與需求

這個專案由使用者以三份原始 prompt 文件依序交付給 Claude Code 執行：UI 需求、OCR 功能需求、搜尋準確率提升需求。以下是三者實際要求的整理版。

> **原始檔案的現況**：三份裡只有 UI 需求那份的原文還在版控裡（[`ui-reference/ui_prompt.md`](ui-reference/ui_prompt.md)）。OCR 與搜尋準確率那兩份（早期文字曾以 `Claude_Code_OCR_影片搜尋開發規劃.md`、`AI_Video_Search_搜尋準確率提升規劃.md` 稱呼）**從未進過版控、目前不存在**，本節的整理版與 [`02-technical-decisions.md`](02-technical-decisions.md) 是它們僅存的記錄。

### 2.1 產品定位與 UI 需求（來自 [`ui-reference/ui_prompt.md`](ui-reference/ui_prompt.md)）

一套本機執行的 Tkinter 桌面應用，讓使用者上傳／下載影片後，用自然語言描述（人物、動作、物件、教學內容）搜尋影片中的關鍵時刻，取代人工逐格瀏覽。四個頁籤：

- **影片與分析**：YouTube 網址下載或選擇本機影片、待分析清單、開始分析。
- **影片庫**：已分析影片列表（可排序／篩選）、摘要、縮圖、詳細資訊、快速跳轉搜尋。
- **搜尋結果**：查詢輸入、結果列表（排名／影片名稱／時間範圍／相似度／命中來源）、詳細分數面板、片段播放、CSV 匯出。
- **處理紀錄**：即時 log 顯示、依等級篩選、複製錯誤、匯出。

全域 Header 顯示待分析／已分析／影片片段／累計成本四張統計卡。要求風格統一（集中管理顏色／間距／字型）、Responsive（1366×768 與 1920×1080 皆可用）。

> **後續更新**：實際開發過程中新增了第五個頁籤「對話搜尋」（多輪對話式搜尋），不在這份原始需求範圍內，是後來才加上的獨立入口。詳見 [`06-conversational-search-flow.md`](06-conversational-search-flow.md)（設計）與 [`07-ui-structure-and-features.md`](07-ui-structure-and-features.md)（Tkinter UI 完整盤點，含此落差的記錄）。**這份 Tkinter 實作後來整個被 Web UI（React + FastAPI）取代並移除**，`07-ui-structure-and-features.md` 保留下來作為歷史設計記錄，實際程式碼已經不存在，見 3.5 節與 [`09-web-ui-migration-plan.md`](09-web-ui-migration-plan.md)。

### 2.2 OCR 功能需求

要求系統能辨識畫面上的文字、保存文字出現的時間區間，並支援文字與語意搜尋，**限定用本地開源引擎**（EasyOCR 為主辨識引擎，Tesseract 為條件式複核引擎，處理型號／比分／數字等規則化文字），明確**不得依賴 Google Cloud Vision、Azure AI Vision 等付費雲端 OCR API**。要求：

- 抽幀策略要避免逐幀執行 OCR（scene change／固定間隔／偵測到文字後 burst mode）。
- OCR 結果建獨立 `ocr_events` 表，不要混入既有的 VLM 描述或 ASR 字幕；要保留 `raw_text`（不可只留修正後文字）、confidence、bbox、`quality_status`、`resolution_method` 等欄位。
- 文字正規化（Unicode／全半形／大小寫／空白）與多引擎融合（不能只取最高 confidence）。
- OCR 建獨立 Retrieval Channel：Exact／Phrase Match、BM25、Fuzzy Match、Embedding Search 都要有。
- 分四個 Phase：Baseline 與設計 → EasyOCR MVP → Tesseract 條件式複核 → Multimodal Retrieval → Production Hardening。
- Engine 用 Adapter／Protocol 包裝，不可讓商業邏輯直接依賴 SDK；單一引擎失敗不可拖垮整支影片。

**已確認的實際落地方式與原始需求的差異**：專案原本已經用 GPT-4o-mini structured output 在既有 VLM 呼叫裡「順便」取得畫面文字（VLM-OCR），這跟本文件要求的「本地開源雙引擎」精神有衝突（本質上是付費雲端 API 做 OCR）。使用者拍板：VLM-OCR 保留不動，新增的 EasyOCR／Tesseract 本地雙引擎定位成**互補**（VLM 只在場景中點抽一張畫面，本地引擎補中點以外時間點的文字），不是取代或比賽準確度。詳見 [`02-technical-decisions.md`](02-technical-decisions.md#本地-ocr-雙引擎easyocrphase-1)。

### 2.3 搜尋準確率提升需求

目標指標：

| 指標 | 建議目標 |
|---|---:|
| Recall@1 | ≥ 75% |
| Recall@5 | ≥ 90% |
| MRR | ≥ 0.80 |
| nDCG@5 | ≥ 0.80 |
| Timestamp IoU | ≥ 0.50 |
| 無答案判斷 F1 | ≥ 85% |
| 搜尋 P95 延遲 | ≤ 2 秒 |

要求先以 Golden Set 測出 baseline，再判斷要不要調整目標；每次實驗只改一個主要變因；不可因為速度改善而接受未量化的準確率下降。建議的目標架構：

```text
查詢分類 → Dense 多向量召回 + BM25/Sparse 召回 + Metadata Filter
        → RRF 融合 → Top 30 Reranker → 相鄰片段合併／Temporal NMS
        → Top 5 必要時由 VLM 驗證 → 門檻判斷與無答案處理
```

分五個 Phase：Phase 0（建立可靠基準）→ Phase 1（低風險高收益：分模態索引、Dense+BM25+RRF、相鄰片段合併、無答案門檻）→ Phase 2（Reranker、動態權重）→ Phase 3（進階視覺／時間理解）→ Phase 4（產品化與治理）。**目前進度落在 Phase 1**，已完成 Dense+BM25+RRF 與無答案信心判斷兩項，詳見 [`01-development-timeline.md`](01-development-timeline.md) 與 [`02-technical-decisions.md`](02-technical-decisions.md)。

## 3. 系統現況

### 3.1 技術棧

| 分類 | 選擇 | 備註 |
|---|---|---|
| 後端 API | FastAPI（`uvicorn`） | REST API，見 `api/`／`services/`／`schemas/` |
| 前端 | React + TypeScript + Vite + Tailwind + TanStack Query | 見 `frontend/`；原本的 Tkinter 桌面 UI 已移除，見 3.5 節 |
| 資料庫 | PostgreSQL 17（Docker，`docker-compose.yml`） | 關鍵字檢索用 `pg_trgm` GIN 索引 ＋ SQL 手算 BM25；`jobs`／`conversations` 表供背景工作與對話狀態持久化。2026-08 從 SQLite 遷移過來，見 [`14-postgresql-migration-plan.md`](14-postgresql-migration-plan.md) |
| ASR | OpenAI Whisper（`whisper-1`） | $0.006／分鐘 |
| VLM（畫面描述＋OCR） | OpenAI GPT-4o-mini | 同一次呼叫回傳描述＋畫面文字，structured output |
| Embedding | OpenAI `text-embedding-3-small` | 原生 1536 維，截短為 1024 維 |
| 本地 OCR | EasyOCR（CPU-only） | 補 VLM 單幀取樣的覆蓋缺口 |
| 場景切分 | PySceneDetect（`ContentDetector`＋`AdaptiveDetector` 聯集） | 本機運算，不花 API 成本 |
| 影片下載 | yt-dlp（`web_embedded` client） | 固定 720p |
| 查詢翻譯 | GPT-4o-mini structured output | 查詢轉中英文兩版本各自比對 |

**Provider 抽象層**：`pipeline/asr.py`／`pipeline/vlm.py`／`pipeline/embedding.py`／`pipeline/translation.py`／`pipeline/summary.py` 對外只暴露跟供應商無關的函式介面，orchestrator（`pipeline/analyzer.py`）不直接呼叫 OpenAI SDK，之後要加其他供應商（例如 Gemini）只需要在各模組內部加實作分支。`segments` 表記錄每筆資料的 `asr_model`／`vlm_model`／`embedding_model`，不同 embedding 模型的向量空間不可混用比較。

### 3.2 模組分層與依賴方向

```text
frontend/（React SPA，透過 Vite dev server proxy 呼叫 /api/*）
  └─ api/*.py（FastAPI router：videos／jobs／search／conversations／stats）
       └─ services/*.py（job_manager 是背景工作序列化與進度持久化；
          video_service／search_service／conversation_service／stats_service
          是薄包裝層）
            └─ pipeline/*.py（analyzer 是 orchestrator，呼叫 scene_detect／asr／vlm／
               embedding／ocr_service／ocr_adapters／frames／summary／translation／
               conversation／evaluation／openai_client）
                 └─ db/（connection／videos／segments／ocr_events／search_log／
                    jobs／conversations）
```

單向依賴、無循環依賴：`db/` 不 import 任何 `pipeline/`／`services/`／`api/`；`pipeline/*` 不 import `services/`／`api/`。這個結構經過四輪重構驗證仍然健康（見 [`02-technical-decisions.md`](02-technical-decisions.md#重構)），Web UI 遷移（見 3.5 節）延續同樣的單向依賴慣例，只在最外層新增 `services/`／`api/`／`frontend/`。原本的 `app.py`／`ui/*.py`（Tkinter）已於 Phase 4 移除，見 [`09-web-ui-migration-plan.md`](09-web-ui-migration-plan.md)。

### 3.3 整體資料流

```mermaid
flowchart TD
    subgraph 下載與待分析
        DL[yt-dlp 下載 / 選擇本機影片] --> PENDING[(videos: pending)]
    end

    subgraph 分析流程（背景執行緒，Queue 回報進度）
        PENDING --> SD[場景切分\nPySceneDetect]
        PENDING --> ASR[音訊轉錄\nWhisper]
        SD --> VLM[逐場景畫面分析\nGPT-4o-mini，批次平行]
        ASR --> VLM
        VLM --> EMB[建立向量\n字幕/畫面/OCR 分開 embed]
        EMB --> WRITE[(segments 表)]
        WRITE --> LOCALOCR[本地 OCR 掃描\nEasyOCR，補覆蓋缺口]
        WRITE --> DOC[整理文件與摘要\nGPT-4o-mini，失敗退回只產摘要]
        LOCALOCR --> EVENTS[(ocr_events 表)]
        DOC --> ANALYZED[(videos: analyzed)]
    end

    subgraph 搜尋流程
        QUERY[使用者查詢] --> TRANSLATE[翻譯成中英文\n各自 embed]
        TRANSLATE --> FILTER[影片層級篩選\n依摘要相關性]
        ANALYZED --> FILTER
        FILTER --> DENSE[Dense cosine 相似度\n字幕/畫面/OCR 三模態取最高]
        FILTER --> SPARSE[BM25/LIKE 關鍵字\nFTS5 trigram]
        DENSE --> RRF[RRF 融合排序]
        SPARSE --> RRF
        SPARSE --> CONFIDENT{{top1 是否被\nsparse channel 印證}}
        RRF --> RESULTS[搜尋結果 + 融合分數]
        CONFIDENT --> RESULTS
    end
```

詳細的各 Phase 邏輯、預算控管、命中來源判斷規則見 [`02-technical-decisions.md`](02-technical-decisions.md)。

### 3.4 成本與限制現況

- 每支影片分析硬上限 **US$0.80**（`analyzer.BUDGET_USD`），只分析 **1 小時以內**的影片（`analyzer.MAX_DURATION_SEC`，超過會被 API 擋下回 422，不會嘗試分析後才中止）。兩個數字的演進：預算 US$0.20 →（VLM 條件式多幀取樣上線）US$0.30 →（長度上限放寬後補調）**US$0.80**；長度上限 20 分鐘 →（2026-08-26）**1 小時**。見 [`02-technical-decisions.md`](02-technical-decisions.md#vlm-條件式多幀取樣) 與 [`11-web-ui-warm-redesign-plan.md`](11-web-ui-warm-redesign-plan.md) §8.11、§8.12。
- **預算與長度上限仍可能衝突**：`BUDGET_USD` 是「跑到哪累加到哪、超過就停」的即時金額，60 分鐘影片的餘裕只有 4.6%（最壞情況外推 $0.765，未實測），撞到上限就變成部分完成——前面的片段仍可搜尋，後半段沒有索引。
- 實測 4～7 支已分析影片（69～160 個場景）的實際花費落在 **US$0.0965～US$0.1885**，都在預算內，沒有觸發過部分完成。
- 搜尋每次呼叫（翻譯＋embedding）都會寫入 `search_log` 表並在 UI 顯示花費，但目前沒有上限或警示機制。

### 3.5 Web UI 遷移進度

專案原本是純 Tkinter 桌面應用，已完成 Web UI 遷移（React 前端 + FastAPI 後端）並移除 Tkinter，現在是純 Web 應用。共用同一套 `pipeline/`／`db/` 邏輯，遷移過程沒有重寫這兩層。詳細架構決策、Job Manager 設計、分階段執行紀錄見 [`09-web-ui-migration-plan.md`](09-web-ui-migration-plan.md)。

**目前進度**：Phase 0～Phase 4 全部完成。`uv run ai-video-search-web` 啟動 FastAPI／uvicorn 後端；`cd frontend && npm run dev` 啟動 React 前端。`ui/`／`app.py`／`theme.py`（Tkinter）已刪除，`07-ui-structure-and-features.md` 保留其設計記錄作為歷史參考。

**~~已知限制~~（2026-08-26 應已解決、待實測確認）**：原本分析工作的進度追蹤是「影片與分析」頁面自己的區域狀態，分析中途切去別的頁籤進度顯示就會遺失。`App.tsx` 改用 keep-alive（造訪過的頁籤留在 DOM 裡不卸載，只是隱藏）之後，五個頁籤切走再切回來狀態都不變，這個限制的根因已經移除；但沒有實跑一輪真實分析確認過，詳見 `11-web-ui-warm-redesign-plan.md` §8.3 與 `09-web-ui-migration-plan.md` 第 9 節。

### 3.6 UI 暖色改版（已完成）

Web UI 遷移穩定後，依 `10-web-ui-ux-warm-responsive-design.md` 的暖色響應式設計規格，對同一套四頁面
進行純視覺／互動層美化（不動 API、資料庫、搜尋邏輯）。分階段執行、技術選型決策、逐項驗收結果見
`11-web-ui-warm-redesign-plan.md`。**目前進度**：Phase 1～Phase 4 全部完成——Design Token＋共用
元件庫＋響應式外殼、影片與分析／影片庫頁面重構、`VideoPlayer`／`SearchResultCard` 共用元件、搜尋
結果／對話搜尋視覺設計、響應式主從版面收合＋鍵盤／對比度品質稽核，四個頁面都已套用新設計並通過
`tsc`／`oxlint`／`build`與 Playwright 瀏覽器驗證。Phase 1–4 之後使用者陸續提出的調整（對話搜尋改
左右並排、YouTube 搜尋移到第一個頁籤並加「播放」／「加入待分析」、頁籤切換不再清空狀態、移除「影片與
分析」頁的新增影片區塊與本機上傳、移除影片庫搜尋列並把「搜尋結果」頁籤改名「搜尋影片」、影片庫預設
選取第一支影片並改成不捲動的固定版面、搜尋影片搜完自動選第一名且預設不自動播放、三頁主從版面統一成
左右各半）記錄在同一份文件的第 8 節。

**目前的加入影片／分析／搜尋流程**（8.4～8.6 之後）：影片一律從「YouTube 搜尋」頁的卡片按
「加入待分析」收進來，分析一律在「影片與分析」頁勾選後送出，自由文字搜尋一律在「搜尋影片」頁進行
——加入、分析、搜尋各只有一個入口。前端已無本機上傳入口（後端 `POST /videos/upload` 仍保留）。
五個頁籤現在依序是 YouTube 搜尋／影片與分析／影片庫／搜尋影片／對話搜尋（`/search` 路由未改名）。

**搜尋範圍改走共用狀態、不經網址**（原本是 `?video_id=`）：影片庫可以勾選任意一批影片，
「在此影片內搜尋」／「在選取影片內搜尋」都透過 `lib/useSearchScope.ts` 設定範圍再導去搜尋頁，
「搜尋影片」與「對話搜尋」兩頁共用同一份——兩頁各留一份 local state 一定會分岔。

**影片庫的詳細面板**：摘要與整理出來的文件（依內容判斷成流程 SOP／教學步驟／課堂筆記／
內容紀錄）在同一段可捲內容裡。文件在**分析時就一起產生**（Phase F，摘要是它的 `overview` 一稿
兩用），面板上那顆按鈕是拿來重新整理的。點文件裡步驟的時間戳會切進**觀看模式**——清單收起來，左邊播放器、
右邊摘要與文件，右欄的時間戳仍可點，邊看邊跳。超出影片長度的時間戳會被停用（實測 8 支文件裡 3 支
有這種對不上的時間戳，見 [`05-known-limitations-and-open-items.md`](05-known-limitations-and-open-items.md)）。

## 4. 接下來看哪一份

依「你想問什麼」導覽的完整索引在 [`README.md`](README.md)，那份文件同時說明了每份文件的性質（現況參考／執行紀錄／原始需求）與是否仍在維護。
