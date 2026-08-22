# 開發歷程

依日期彙整已完成的開發內容。每個項目只保留「做了什麼、為什麼、驗證結果」的重點，詳細的技術取捨與比較留給 [`02-technical-decisions.md`](02-technical-decisions.md)。

## 2026-08-18：UI 重寫與 Pipeline V0

### 全域 UI 骨架

- 建立集中管理的 Theme（顏色、8px 間距系統、字型、`ttk.Style`）、共用小型元件（`StatCard`／`EmptyState`／`Badge`／`SimilarityBar`／可捲動 Treeview）、全域 Header（四張統計卡）、主視窗與四頁籤 Navigation。
- 開發環境問題：`uv` 自動下載的 standalone Python 在 WSL2+WSLg 上 `tkinter` 找不到 CJK 字型，中文全部顯示空白。修法：強制 `uv` 使用系統 Python（`pyproject.toml` 的 `python-preference = "only-system"`）。

### YouTube 下載＋待分析清單（真實功能）

- `downloader.py` 包 `yt-dlp`，固定 720p，背景執行緒下載＋Queue 回報進度。
- **修正下載 403 Forbidden**：YouTube 對多數 player client 要求 PO Token 才能取得影片本體，改用不需要 PO Token 的 `web_embedded` client，並加上 `js_runtimes: {"node": {}}` 解簽章挑戰（新增系統依賴 `node`，已用 v22.22.1 驗證）。

### 「開始分析」核心 Pipeline V0（真實功能）

打通「下載 → 分析 → 寫入索引 → 能被找到」的最短路徑：`scene_detect.py`（PySceneDetect）、`asr.py`（Whisper）、`vlm.py`（GPT-4o-mini 畫面描述）、`embedding.py`（`text-embedding-3-small`，字幕與畫面**分開** embed）、`analyzer.py`（background thread orchestrator，Queue 回報進度，超過 US$0.20 立刻停止並標記部分完成）、`search.py`（brute-force cosine，取較高分排序）。

驗證：真實 YouTube 影片（19 秒 "Me at the zoo"）跑通全流程，`segments` 正確寫入，花費 US$0.0025，搜尋語意排序正確（「大象」相似度 0.51 vs「棒球比賽」相似度 0.15）。

### 修正 AV1 場景切分失效

`web_embedded` client 抓到的 720p 影片常是 AV1 編碼，PySceneDetect 預設的 `opencv` backend 沒有硬體加速時對 AV1 完全讀不到畫面，誤判成「整支影片只有一個場景」。改用 `ffprobe` 先偵測編碼，AV1 才切換 `pyav` backend（新增依賴 `av`，較慢，602 秒影片需 79～85 秒）。602 秒影片原本誤判成 1 個場景，修正後正確找到 19 個。

### 進度百分比（音訊轉錄＋場景切分）

Whisper API／PySceneDetect 都不提供伺服器端進度，改用背景執行緒等待期間依經驗校準的預估時間定期回報百分比（上限顯示 95%，避免顯示到 100% 但還沒真的完成）。

### 影片庫頁籤（真實功能）

`pipeline/summary.py`（GPT-4o-mini 產生 3～5 行摘要）、`list_library_videos()`（`analyzed`＋`failed` 都顯示）、影片庫列表（排序／篩選／縮圖／詳細面板／「重新產生摘要」／「在此影片內搜尋」）。過程中修掉兩個真實 bug：

1. **Tk `<<TreeviewSelect>>` 事件是非同步派發的**：`refresh()` 為保留選取重新 `selection_set()` 同一列，會觸發延遲的 select 事件，把剛顯示的「✓ 摘要已更新」訊息洗掉。修法：只有「使用者真的選了不同影片」才清暫時性訊息。
2. **影片庫沒有即時顯示新分析完的影片**：自動刷新原本只綁在切換分頁那一刻，如果分析完成當下使用者剛好停在影片庫分頁就不會更新。修法：`_on_stats_changed()` 統一觸發 `library_tab.refresh()`。

### Whisper 信心分數欄位（只做擷取，未做過濾）

發現背景音樂被 Whisper 轉錄成大量重複歌詞，污染字幕 embedding。這次先把 Whisper API 本來就有回傳、但先前沒儲存的 `no_speech_prob`／`avg_logprob`／`compression_ratio` 存進 `segments` 表，過濾邏輯留到 08-20 才做（見下方「Whisper 幻覺字幕過濾」）。

### OCR（畫面文字）支援

用 OpenAI structured output 讓 GPT-4o-mini **在同一次 VLM 呼叫**裡同時回傳畫面描述與畫面文字，不需要傳統 OCR 引擎、成本幾乎不變。所有 embedding 向量統一設定成 **1024 維**（`text-embedding-3-small` 原生 1536 維，用 API 的 `dimensions` 參數截短）。

---

## 2026-08-19：本地 OCR 與搜尋強化

### 本地 OCR 雙引擎 Phase 1（EasyOCR MVP）

補上 VLM-OCR 只在場景中點抽一張畫面、可能漏掉其他時間點文字的缺口。新增 `pipeline/frames.py`（共用抽幀）、`pipeline/ocr_adapters.py`（`OcrEngine` Protocol＋`EasyOcrEngine`，`lru_cache` 單例）、`pipeline/ocr_service.py`（場景內固定間隔取樣＋正規化＋去重合併）、`ocr_events` 表。**這是專案第一次有自動化測試**（`pytest` 加入 dev dependency，15 個 unit test）。

端到端驗證：自製測試影片（文字只在 1～3 秒可見，VLM 中點在 6 秒抓不到），本地 OCR 在 2 秒取樣點正確抓到文字（confidence 0.996），搜尋正確以 `hit_source='OCR'` 命中，沒有污染其他模態分數。花費 US$0.00168。

### 場景切分改用多 Detector 聯集

`ContentDetector` 單獨會漏掉漸進式轉場（溶接／crossfade）。改用 `ContentDetector`＋`AdaptiveDetector`（PySceneDetect 的多 detector 是聯集關係：任一個判定切就切）能正確抓出中間漏掉的切點。曾評估加 `ThresholdDetector`，因誤切率偏高而不採用（見 [`03-excluded-approaches.md`](03-excluded-approaches.md)）。602 秒測試影片場景數從 19 增加到 33，耗時幾乎沒差（88.5s vs 校準值約 85s）。

### 場景長度正規化（merge/split）

原始場景長度落差極大（0.1～129.76 秒都有）。新增兩個 pass：合併太短場景、切開太長場景，收斂到約 6～12 秒。33 個原始場景 → merge 後 21 個 → split 後 69 個，96%（66/69）落在 6～12 秒範圍內。

### 搜尋支援中英文雙語查詢

查詢先翻譯成中英文兩個版本各自 embed，每個模態取兩者較高分。實測跨語言比對（英文畫面描述 vs 中文查詢「警告標誌」）分數從 0.5624（不翻譯）提升到 0.6704（翻譯後）。

### 自動摘要（Phase F）＋搜尋依摘要篩選影片＋搜尋成本追蹤

三件相關的事一起做：`analyzer.py` 新增 Phase F 自動產生摘要；`search()` 新增 `_relevant_video_ids()`，全域搜尋先依影片摘要（無摘要退回標題）篩選相關影片；新增 `search_log` 表追蹤每次搜尋花費。**實測抓到真的門檻校準問題**：短標題估出的 `MIN_RELEVANCE=0.25` 對長摘要文字太嚴格（明確相關查詢的最高分只有 0.22），改成以相對差距 `RELEVANCE_MARGIN=0.15` 為主要判斷依據，詳見 [`02-technical-decisions.md`](02-technical-decisions.md#影片層級篩選)。

---

## 2026-08-20：搜尋準確率 Phase 1、平行化、重構

> 這天的工作目前散落在各規劃文件自己的「狀態」列，`development-log.md` 的索引尚未更新到這天，此節統一補上。

### Golden Set 定案與 Evaluator

修正 CSV 編碼，刪除有資料矛盾的 `gs-009`，定案為 17 題（13 題 answerable、4 題 no-answer）。新增 `pipeline/evaluation.py`：Recall@K、MRR、nDCG@K、Timestamp IoU、No-answer F1，純邏輯評分函式與需要真實 API 的整合函式分離。詳見 [`04-testing-and-evaluation.md`](04-testing-and-evaluation.md)。

### Hybrid 檢索（Dense + BM25 FTS5 trigram）+ RRF 融合

`search.py` 排序從純 dense cosine 改成 RRF（Reciprocal Rank Fusion）融合 dense 排名與 BM25/LIKE 關鍵字排名。掃過 `RRF_K` = 60/20/10/5 四個值，隨 k 變小持續單調變好，定案 **`RRF_K=5`**。對照 baseline：Recall@1 0.538→0.615、Recall@5 0.692→0.846、MRR 0.628→0.722、nDCG@5 0.636→0.746、Mean IoU 0.725→0.773，全部超過純 dense baseline。詳見 [`02-technical-decisions.md`](02-technical-decisions.md#hybrid-檢索與-rrf-融合)。

### 無答案信心判斷

`no_answer_f1` 原本用借來的 `MIN_RELEVANCE` 門檻恆為 0。探索四種訊號後，只有「top1 是否同時被 sparse channel 印證」這個布林訊號能把 answerable／no_answer 兩組分開。新增 `SearchResponse.is_confident`，`no_answer_f1` 從 0.000 提升到 **0.667**，Recall@5／Mean IoU 完全不受影響。已知限制：無法處理否定句。

### 場景長度目標帶收窄：6～12 → 9～12 → 8～12 秒

使用者希望片段更完整，先試 9～12 秒，發現命中率不升反降（67.7%～91.1%），根因是數學上的「死區」（`SPLIT_ABOVE_SEC` 不再等於 `2×MERGE_BELOW_SEC`）放大了既有邊界情況，順便修掉這個被放大的 bug。改成 8～12 秒後命中率回升到 78.8%～91.4%，下限保證兩支測試影片都是 100% 沒違反。**這個常數變更讓 golden-set.csv 既有的時間戳基準需要重新產生**，詳見 [`04-testing-and-evaluation.md`](04-testing-and-evaluation.md#5-評測-baseline-的時效性警示)。

### 影片下載平行化實驗（aria2c）—已放棄

嘗試用 aria2c 多連線加速下載，實測反而比原生單連線下載器慢 4～7 倍（15.8s vs 65.6s/109.1s）。已回滾，詳見 [`03-excluded-approaches.md`](03-excluded-approaches.md)。

### 分析流程平行化（Tier 1 + Tier 2）

在不改變任何判斷結果的前提下縮短分析耗時：Tier 1（零風險）— 場景切分＋音訊轉錄同時起跑、片段內三個 embedding 平行送出、本地 OCR＋產生摘要同時起跑。Tier 2 — VLM 逐場景畫面分析改成批次平行（`VLM_BATCH_SIZE=5`，依真實撞過的 TPM 上限回推）＋新增 rate limit 重試機制。真實效能驗證：20 個真實場景，批次平行 13.2 秒 vs 循序估算 57.3 秒，**加速 4.35 倍**，0 次撞 rate limit。詳見 [`02-technical-decisions.md`](02-technical-decisions.md#分析流程平行化)。

### UI：新增「融合分數」欄位

使用者發現搜尋結果排名沒有依照畫面上「相似度」欄位由高到低排序，追查後確認是刻意設計（排序依 RRF 融合分數，相似度只顯示 dense cosine 分數，兩者本來就是分開的數字）。`SearchResult` 新增 `fusion_score` 欄位，UI 結果列表／詳細面板／CSV 匯出都新增「融合分數」對照顯示，避免使用者誤讀。

### 重構（第一輪＋第二輪）

依 `.claude/skills/refactor/SKILL.md` 進行兩輪不改變外部行為的重構：

- **第一輪（Step 1～9）**：刪除死碼（`mock_data.py`、未使用函式）、抽出共用的 `pipeline/progress_estimation.py`（場景切分與音訊轉錄的背景執行緒＋預估進度邏輯，原本逐字重複）、`db.py` 拆成 `db/` 套件（`connection`／`videos`／`segments`／`ocr_events`／`search_log`，對外 API 不變）、`analyzer.py` 的 `_analyze_worker()` 拆成具名 phase 函式、新增特徵測試（`test_db.py`／`test_analyzer_integration.py`）、`development-log.md`（原 35KB 單檔）依日期拆成 `changelog/`。UI 輪詢骨架抽取（原規劃的 Step 10）評估後判斷效益低於風險，**明確決定不做**。
- **第二輪**：修正 3 處指向已搬移文件的殘留註解引用；補上 `search._hit_source()` 的測試；抽出 `openai_client.chat_completion_cost()` 共用 helper，取代 `vlm.py`／`summary.py`／`translation.py` 三處逐字重複的成本計算公式；`analyzer.py` 的 `segment_rows` 從無型別 9-tuple 改成具名 `_SegmentRow` dataclass。兩輪重構全程遵守「先分析、確認後才動手、一次只做一步、每步都跑測試驗證」的流程；第二輪結束時全專案 150 個測試（不含需要真實 API 的 `integration` 測試）全數通過。
