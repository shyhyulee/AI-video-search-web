# 開發歷程

> **類型**：開發歷程｜**狀態**：持續追加新條目
> 分類說明與完整索引見 [`README.md`](README.md)。

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

> 這天的工作原本散落在各規劃文件自己的「狀態」列，此節統一補上。（當時的 `development-log.md` 索引只更新到 08-19，該檔案與 `changelog/` 現已不存在，本文件是唯一的開發歷程記錄。）

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

## 2026-08-26：第三輪重構

> 2026-08-21～25 的 Web 化（Tkinter → FastAPI + React）與 UI 暖色改版記錄在
> [`09-web-ui-migration-plan.md`](09-web-ui-migration-plan.md) 與
> [`11-web-ui-warm-redesign-plan.md`](11-web-ui-warm-redesign-plan.md)，本檔未逐項收錄。

### 重構（第三輪）

依 `.claude/skills/refactor/SKILL.md` 進行第三輪不改變外部行為的重構。這一輪的範圍是**Web 化之後長出來的東西**：新增的 services／schemas／api 三層，以及在遷移期間成長到 697 行的 `analyzer.py`。分三波共 8 個 commit，測試從 266 增加到 **326**：

- **波 A（安全網，先補測試不動正式碼）**：`job_manager` 是全專案唯一有 process 級共享狀態（分析 slot 旗標＋鎖）與 pump thread 的模組，卻只有 HTTP 層的間接測試；`search()` 的 helper 全都有測試，但「串起來之後」的行為沒有。補上 `test_job_manager.py`（27 支）與 `test_search_pipeline.py`（17 支），後者用真實臨時 SQLite（含 FTS5 bm25），只把兩個 OpenAI 呼叫換掉，向量刻意用 4 維讓 cosine 值可人工推算。兩支都做過突變測試確認不是空轉。
- **波 B（結構）**：① `GET /api/v1/videos` 為了算三個布林旗標而載入每支影片的全部 segment（含 embedding BLOB），改成一句聚合查詢，實測 **47.5ms → 0.7ms**、省下每次請求約 4.5MB 的 BLOB 讀取；② `analyzer.py` 的進度回報、成本累加與預算判斷三個橫切關注點原本靠參數手工穿線（`total_cost` 出現 43 次、進度雙寫 23 處），收進 `_AnalysisContext`（**43 → 7**，`_run_vlm_phase` 參數 7 → 3）；③ 兩處手工「Thread ＋ holder dict ＋ 手動重拋」改用 `ThreadPoolExecutor`，全檔只剩一種併發寫法；④ `search.py`（522 行單檔、`search()` 一個函式做六件事）拆成 `pipeline/search/` 七個模組，依賴單向無環，對外 import 路徑完全不變。
- **波 C（一致性）**：例外型別從 `job_manager` 搬到 `services/errors.py`（API 原本有 5 處拿 `job_manager.VideoNotFoundError` 表達「影片找不到」）；API 層 6 處繞過 service 直呼 `db` **收斂為 0**，順帶消掉 4 個 `assert`（`python -O` 下會整個消失）；補上全專案第一份 logging 設定（在這之前所有訊息只能靠 lastResort handler 印出，INFO 完全看不到），5 處 eager f-string 改 lazy `%`、3 處沒有 consumer 的 `extra={…}` 移除；20 處引用早已移除的 Tkinter UI 的註解（15 個檔案）全部改寫成目前實際成立的說明，README 修正 6 處與程式碼不符之處（其中預算上限仍寫 US$0.30，實際已是 $0.80）。

**C0（缺陷修正，不算重構）**：分析中發現 `_analyze_worker()` 在自己的 try 之外做了五件可能拋例外的事（`get_client()` 在缺 API 金鑰時會直接拋），一旦拋出就不會送出終端事件，job_manager 的 pump thread 會永遠停在 `queue.get()`、分析 slot 永不釋放，**之後每一支影片都卡在 queued，只能重啟伺服器**。因為是行為變更所以獨立一個 commit：worker 拆成兩層保證一定送出剛好一個終端事件，pump 的釋放 slot 移進 `finally`。

**驗證方式**：除了全套測試，每個結構性步驟都做了新舊實作的等價比對——`analyzer` 重播完整 worker 比對事件序列／狀態寫入／DB 呼叫／總花費（正常與預算截斷兩條路徑）；`search` 用 9 組查詢（含否定句、泛用詞、指定影片、top_k 截斷）逐欄位比對；模態旗標在真實 `app.db` 上比對 10 支影片。最後三個 commit 在提交前各自匯出成獨立副本跑過完整測試，確認**單獨 checkout 每個 commit 都是綠的**——這個做法也因此抓到兩個原本測試裡的錯誤（`monkeypatch.undo()` 連 fixture 的 `db.DB_PATH` 一起撤掉，因為主目錄剛好有 `app.db` 而一路綠燈）。

**刻意不做**：不引入 Repository／DI container／CQRS（目前規模下 15 個 `db.*` 直呼更好讀）；不移除 `video_service` 的 11 個一行透傳（刪掉會讓 API 層直接依賴 db，方向更差）；`progress_estimation` 不改用 executor（它的 worker 是 `daemon=True`，換掉會讓分析途中 Ctrl-C 要等 ffmpeg／Whisper 跑完）；不修正本地 OCR 失敗時已花費用被丟棄的既有低估（那是行為不是結構債，已在程式碼註解標記）。

完整的任務看板（含每張卡的驗證方式、刻意不做的理由，以及過程中做錯／走錯的記錄）見 [`refactor-board.html`](refactor-board.html)。

## 2026-08-27：資料庫從 SQLite 遷移到 PostgreSQL

完整計畫、決定理由與執行紀錄見 [`14-postgresql-migration-plan.md`](14-postgresql-migration-plan.md)，
逐階段進度看板見 [`pg-migration-board.html`](pg-migration-board.html)。這裡只記時間軸摘要。

**動機不是效能**：22 支影片／931 個片段，SQLite 完全夠用。真正的理由有兩個——專題發表需要
一個能講的技術主題，以及為之後上 pgvector 鋪路。這點在計畫文件裡寫明，沒有包裝成效能優化。

**條件很好**：`db/` 是全專案唯一碰 SQL 的地方（`db/` 以外沒有任何 `sqlite3` import 或查詢語句），
所以 `services/`／`pipeline/`／`api/` 三層**一行都沒有因為換資料庫而改動**。沒有 ORM 要重寫、
沒有 migration 歷史要轉換。

**技術選型**：Docker 跑 `pgvector/pgvector:pg17`（port 5433 避開機器上另一份 PostgreSQL）、
`psycopg` 3 搭配手寫 SQL（不引入 SQLAlchemy／Alembic——`db/` 已經是乾淨邊界，改 ORM 是另一個
獨立專案，綁在一起會讓「搜尋結果變了」無法歸因）、embedding 維持 `BYTEA` 不換成 `vector` 型別
（pgvector extension 有裝好，但欄位型別留給之後獨立的一步）。

**最大的收穫是刪掉東西**：FTS5 虛擬表換成 `segments.content` 這個 generated column ＋ `pg_trgm`
GIN 索引之後，`backfill_fts()`／`prune_orphan_fts()`／`delete_for_video()` 的 FTS 同步／
`insert_segment()` 的第二次寫入四段程式碼全部消失，連同 `migrate_columns()` 與兩支
`_row_to_record()` 裡 9 處 `if "x" in keys` 防呆——`db/` 從 1348 行降到 1231 行。
更重要的是根除了一整類 bug：FTS5 的 rowid 靠呼叫端自己同步，漏掉就留下殘留列，實測曾有
**925/1795（52%）**是對不到片段的殘留列，佔掉 bm25 前 200 名額、把真正命中的片段擠出候選集。
generated column 由資料庫維護，這種脫節在結構上不可能發生。

**檢索的替代方案**：PostgreSQL 沒有 FTS5，`to_tsvector` 對中文有一樣的斷詞問題，所以同樣走
trigram 路線，BM25 分數在 SQL 裡自己算（k1=1.2、b=0.75 對齊 FTS5 預設值，分數加負號維持
「越小越相關」的既有介面契約）。保住 IDF 是重點——`sparse.py` 的短詞比例門檻整套建立在
「長詞有真實 IDF 加權」的前提上。

**驗收**：動工前先在 SQLite 上跑一次 golden set 存 baseline（切換後就沒有 SQLite 環境可比了），
遷移後跑同一份 18 題對照：

| 指標 | SQLite | PostgreSQL |
|---|---|---|
| Recall@1／Recall@5／nDCG@5／IoU／No-answer F1 | — | **完全相同** |
| MRR | 0.5085 | 0.5077（−0.0009） |

那 0.0009 沒有用「在誤差內」帶過：逐題比對後確認**只有 gs-012 一題**的正解從第 9 名掉到
第 10 名，13 道可回答題目平均下來正好是這個數字，而 9 和 10 都在 top-5 之外。再進一步做了
不含 LLM 的隔離比對（相同取詞分別打 SQLite FTS5 與 PostgreSQL），確認**召回集合完全一致**
（26 vs 26、93 vs 93），差異只在同一批候選集內部的排序——兩套 BM25 實作的預期落差。

資料搬遷保留原 id（golden set 與既有對話都直接引用），2338 個向量／9,576,448 bytes 逐位元組
比對相符。實跑 app 走完八個流程（讀取／搜尋／多輪對話／狀態持久化／上傳分析／重新分析／刪除／
YouTube 下載）共 117 個請求、0 個錯誤。測試從 336 支增加到 337 支、全數通過，隔離方式從
「每測試一個臨時 SQLite 檔案」換成「共用 `avs_test` 資料庫 ＋ 每測試 TRUNCATE」，並加了
一道「資料庫名稱必須以 `_test` 結尾才准 TRUNCATE」的防護——正式資料庫現在裝著真實分析結果，
一次 DSN 組法的錯誤就是無聲的資料全毀。

**順手修掉兩個 SQLite 時期就存在、只是沒被觸發的問題**：查詢字串裡的 `%` 沒有跳脫（會變成
「比對任意字串」、一次撈出全部片段），以及 `fts_like_search()` 的 `LIMIT` 沒有 `ORDER BY`
（PostgreSQL 不保證回傳哪幾列，而呼叫端要拿結果算比例門檻）。

## 2026-08-29：影片庫的主題分類與庫內搜尋

參考 YouTube 首頁的「搜尋列＋主題 chips」（`YT_01.png`），在「影片庫」頁籤加上主題分類與庫內搜尋。
完整記錄見 [`11-web-ui-warm-redesign-plan.md`](11-web-ui-warm-redesign-plan.md) §8.17。

**選了最便宜的那條路**：分類用**關鍵字規則**從「標題＋摘要」推導，固定 10 類，整件事就是前端一個
新檔 `lib/videoCategory.ts`——**不改後端、不改資料庫、不呼叫 LLM、不花任何 API 成本**。AI 自動分類
是被權衡掉的，不是不可行（摘要已經存在，23 支合計不到 US$0.01），但它要加欄位、要回填、analyzer
要多一次呼叫；日後要換過去的改動面也很小：`classifyVideo()` 換成讀後端回傳的欄位，UI 一行不動。

**字典是對著真實資料調出來的，不是憑空寫的**。先用一次性腳本連 PostgreSQL 把 23 支已分析影片跑過
一輪，調了兩輪後 **23／23 全部分對、0 支落到「其他」**：第一版把類別叫「程式與教學」，害
`100 Animals in Chinese` 這種語言教育影片被類別名本身排除；另外收掉四個過鬆的關鍵字
（`skills`／`goal`／`名稱`／`bmw`），拿掉後仍是 23／23，**證明它們沒有貢獻、只帶來誤判風險**。

**搜尋是庫內篩選，不是把 §8.6 的決定推翻**：§8.6 剛移除過影片庫的搜尋列，但那條是「把字帶去
`/search` 做語意檢索片段」的捷徑；這條只比對已經在手上的標題與摘要，邊打邊篩、不打 API、不跳頁。
要守的規則是「**語意搜尋只有『搜尋影片』頁一個入口**」，沒有被破壞——也因此否決了「找不到結果時
給一個按鈕跳去語意搜尋」的提案。

Playwright 實跑 32 項全過（chips 分佈與事前驗證完全一致、「半導體」靠摘要命中 2 支標題沒有這三個
字的影片、chips 數量不隨打字跳動、四種空狀態文案、390px 無溢位、零 console error）。

**已知天花板**：字典就是上限，題材差很多的新影片會一路掉進「其他」，直到有人補關鍵字。判斷「該補
了」的訊號很明確——「其他」那顆 chip 的數量開始追上其他類別。

## 2026-08-29：搜尋範圍支援多選影片

搜尋範圍從「全部影片／單一影片」放寬成**任意一批已分析影片**。決策背景與實測數據見
[`02-technical-decisions.md`](02-technical-decisions.md#搜尋範圍從全部單一影片放寬到任意子集)，
行為規格見 [`12-search-query-logic.md`](12-search-query-logic.md) §2／階段 1／階段 4。

**五個定案決策**：入口放在影片庫（每列勾選＋底部「在選取影片內搜尋」，單支的「在此影片內搜尋」
變成「勾一支」的捷徑）；有指定範圍就**不套用影片層級篩選**（選了就全查，跟單支的舊行為一致）；
對話搜尋**共用同一份範圍**；BM25 的範圍下推**單選多選一起修**；UI 勾選的範圍對 LLM 是**硬邊界**。

**真正的技術重點是順手挖出來的既有缺陷，不是型別從 `int` 改成 `int[]`**。sparse channel 的 SQL
完全沒有 `video_id` 條件——它在**全庫**取 BM25 前 200 名，才由 Python 端用範圍過濾。而 `LIMIT`
是排序之後才截斷的，所以限定範圍搜尋時範圍外的片段會先把名額佔走，sparse channel 整個落空、
RRF 只剩 dense 一路、`is_confident` 恆為 false。**這個缺陷單支影片的舊行為就有**，多選只是讓它更
容易觸發。解法是在 `_BM25_SQL` 前面加一個 `scope` CTE；`video_ids` 為 `NULL` 時語意逐字不變。

踩到兩個 PostgreSQL 的坑：`scope` 被引用兩次，預設會被**物化**、`content` 的 pg_trgm GIN 索引就
吃不到，必須標 `NOT MATERIALIZED`；`stats` 也要讀 `scope`，只縮 `df`／`hits` 會讓 IDF 的分母還是
全庫文件數、分數整個灌水。

**對話搜尋的硬邊界規則**：LLM 解析出的範圍只能在使用者勾選的範圍內**再收窄**（取交集），不能擴張
出去；交集為空（LLM 認錯影片）就整個忽略這次收窄、退回勾選的範圍，而不是回零筆。理由是勾選是明確
的使用者操作——畫面上勾著 3 支、實際卻搜了第 4 支，使用者沒有任何線索可以除錯。收窄了會把實際
生效的範圍回傳給前端（`ConversationTurnOut.video_ids`）並顯示在狀態列。範圍由前端**每輪重送**、
刻意不存進 `conversations` 表：它屬於「使用者現在看的畫面」，存起來的話在影片庫改了勾選、回到對話
還會沿用舊範圍。

**前端改用共用 context 而不是 URL 參數**：舊做法是 `/search?video_id=…&video_title=…`，但範圍現在
要給「搜尋影片」與「對話搜尋」兩頁吃，兩頁各自從 URL 解析一定會分岔。改成
`lib/useSearchScope.ts`（只存 id，標題從 react-query 的 `['videos','library']` 快取查，跟影片庫同
一個 query key、不會多打 API）。`VideoListItem` **一行都不用改**——它的 checkbox 本來就是「有傳
`onCheckedChange` 才 render」，影片庫補傳 props 就長出來了。

**實跑驗證**（Playwright 驅動真實 app）：勾 2 支 → request body `video_ids:[28,8]` → 15 筆結果
全部只來自那 2 支、無範圍外洩漏 → 移一顆 chip 變 1 支 → 切到對話頁範圍相同 → 切回來範圍與結果
都還在（keep-alive）→ 零 console error。另跑一次真實對話輪次（`video_ids:[8]`），6 筆結果全來自
video 8、回傳的生效範圍是 `[8]`。**top1 融合分數 0.25**，遠高於「只有 dense 命中」的上限 0.1667，
證明 sparse channel 真的活著。**成本**：同句查詢全域 US$0.00016、限定範圍 US$0.00004。

**刻意沒做**：`search_log` 不加範圍欄位。它現在的契約是「使用者原始 query＋花費」，加欄位要一併
決定歷史列怎麼填、範圍算不算稽核軌跡的一部分，跟這次的功能無關。

**已知天花板**：範圍下推只解決「限定範圍」的情形，**全域搜尋的 200 名額截斷還在**。而且限定範圍
這條路徑**從來沒進過 golden set 評測**（`evaluation.py` 不傳範圍參數，17 題全是全域搜尋），所以
「選了 N 支之後的準確率」改動前後都是未知數；反過來說全域路徑的 SQL 語意逐字未變，既有 baseline
沒有失效、不需要重跑。

## 2026-08-29：把影片內容整理成一份結構化文件

補上「摘要」與「單一片段」之間缺的那一層：整支影片的素材整理成一份可交付的文件——工廠影片產出
生產流程 SOP、烹飪影片產出教學步驟、課程產出課堂筆記。決策背景與實測數據見
[`02-technical-decisions.md`](02-technical-decisions.md#影片內容整理成文件)。

**規劃階段先查真實資料庫，結果直接改掉了設計**。使用者舉的兩個範例，素材結構正好相反：工廠影片
（video 31）的流程知識全在**字幕**、畫面描述是雜訊；烹飪影片（video 13）反過來——字幕是 Whisper
在純音樂上產生的**幻覺俄文**（`Девочка-пай`、`Редактор субтитров А.Семкин`），流程全在畫面。
加上覆蓋率（無畫面描述 1/1,156、無字幕 150/1,156），得到 prompt 的三條硬要求：每步必須有時間戳、
**字幕與畫面矛盾時以畫面為準**、不適合就選 `content_log` 不要硬掰。

**跟摘要最大的差別是用了 `ocr_text`**。那個欄位覆蓋率 93%（1,076/1,156），`summary.py` 完全沒碰。
壽司那支證明它是決定性的：產出的文件裡「上方保留 3 公分」「靜置 10 分鐘讓壽司釋放」逐字來自畫面
字卡——那支字幕全壞、畫面描述只說得出「捲起來」，不帶 OCR 會產出一份沒有份量也沒有時間的空洞
食譜。組 prompt 時順手發現 **21 個片段的 `ocr_text` 是字面字串 `"null"`**，濾掉但沒回填資料庫。

**刻意不抄摘要的 `segments[:200]` 硬截斷**：摘要截掉尾段只是不完整，SOP 截掉尾段會默默少掉最後
幾個製程步驟，比直接失敗更糟。實測最大 112 段、1 小時上限也只到約 360 段，context 放得下。

**第一版被敘事形式騙走**。實跑時 video 31 被判成 `content_log` 而不是 `sop`——內容完全正確（章節
就叫「主板生產線」，步驟是塗矽膏 → 貼片機 → 測試 → 包裝），只有型別錯了，因為那支是第一人稱參觀
敘事（「我是翼王，這次來帶大家參觀」），模型看形式不看內容。prompt 補一條「`content_log` 是最後
退路，判斷看內容不看敘事形式」之後，四種類型全部判對，而且球賽那支**沒有被過度矯正**成硬掰的
打擊 SOP。

**兩個估計都估錯了，而且是往好的方向**：規劃時估成本 US$0.005/份、耗時 20～40 秒；實測成本
**US$0.0004～0.0026**（5／33／65 個片段的三支），耗時 **7.5 秒**。所以維持同步 REST、沒有開第三種
job type 是對的——那會踩到 `retry_job()` 讓新 type 靜靜掉進 download 分支的既有地雷。

**加回一個最小的 schema migration**。PostgreSQL 遷移時 `migrate_columns()` 被整個移除，理由是
「全新資料庫、一次定義齊全」。這次加三個欄位證明那個前提只在遷移當下成立：`CREATE TABLE IF NOT
EXISTS` 對既有資料庫是 no-op，`_row_to_record()` 直接 `KeyError`——實測就是這樣讓 14 個測試同時
掛掉的。`create_table()` 現在多三行冪等的 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`，不需要任何
人手動下 SQL。

Playwright 實跑：四顆按鈕、「摘要／整理文件」頁籤共用同一塊捲動區、既有文件正確載入（只打 GET、
沒有誤觸重新產生）、時間戳靠右對齊、零 console error。

**已知天花板**：**文件品質沒有任何量化方式**——搜尋有 golden set，這個只能人工看，代表之後改
prompt 沒有回歸測試可擋。幻覺步驟的風險只是被緩解（時間戳強制 + uncovered 欄位），4 支的樣本不是
保證。步驟的時間順序完全靠模型自己排，實測 video 29 出現過 `[00:48]` 排在 `[00:38]` 前面。
