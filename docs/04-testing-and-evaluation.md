# 測試與驗證

> **類型**：現況參考｜**狀態**：維護中，跟著程式碼更新
> 分類說明與完整索引見 [`README.md`](README.md)。

## 1. 測試套件現況

專案在 08-19 才第一次導入 `pytest`（本地 OCR 雙引擎 Phase 1 開發時），此後每個功能都同步補測試。目前有兩套：

- **後端 `pytest`：30 個檔案、410 個測試**，全部是不呼叫真實 API 的純邏輯／mock 測試（`uv run pytest` 預設執行），另有 1 個需要真實 API 的整合測試（`integration` marker，預設不執行）。
- **前端 Playwright e2e：4 個檔案、32 個檢查**（`cd frontend && npm run test:e2e`）。第四輪重構之前前端**一個測試都沒有**，見 [`01-development-timeline.md`](01-development-timeline.md) 的第四輪重構。

> 下表的數字會隨開發變動，重點是**涵蓋範圍**而不是精確筆數。要現況數字跑
> `uv run pytest --collect-only -q`。

### 1.1 後端：pipeline

| 測試檔案 | 測試數 | 涵蓋範圍 |
|---|---:|---|
| `test_search.py` | 49 | `best_score()`／`select_relevant_ids()`／`extract_terms()`／`rrf_scores()`／`hit_source_label()`／否定句切分與排除，純向量與邏輯運算，不呼叫 API |
| `test_search_pipeline.py` | 20 | `search()` 端到端特徵測試：真實臨時資料庫，只把兩個 OpenAI 呼叫換掉，向量刻意用 4 維讓 cosine 值可人工推算 |
| `test_analyzer.py` | 28 | 本地 OCR 場景過濾、Phase C 平行 embedding 的 budget 截斷時機、Phase E／F 平行執行的失敗隔離與成本加總、Phase B 批次平行的場景順序保證與 rate limit 重試 |
| `test_media.py` | 18 | 五個 ffmpeg／ffprobe 呼叫端的命令列逐字鎖定、每一處都有 timeout、超時的失敗語意 |
| `test_ocr_service.py` | 15 | 文字正規化、場景內取樣邊界、事件去重合併 |
| `test_scene_detect.py` | 13 | merge/split 合併門檻邊界、結尾殘留片段處理、均分切割邊界對齊、無場景切換 fallback |
| `test_segment_material.py` | 11 | 摘要與文件共用的素材格式：欄位順序、`include_ocr` 開關、佔位字串過濾、時間戳 |
| `test_asr.py` | 10 | 幻覺字幕模式 A／B 的判斷邏輯（合成資料） |
| `test_document.py` | 8 | doc_type 判斷、片段數上限、prompt 組裝與成本計算 |
| `test_intent.py` | 7 | 對話意圖判斷的 schema 解析與退回邏輯 |
| `test_vlm.py` | 6 | 畫面描述的成本計算特徵測試（mock OpenAI client＋`frames.extract_frame`） |
| `test_progress_estimation.py` | 5 | 共用的背景執行緒＋預估進度 helper（假 `work()` callable） |
| `test_ocr_adapters.py` | 4 | EasyOCR adapter 輸出轉換（假 reader 物件，不下載真實模型） |
| `test_translation.py` | 3 | 查詢翻譯的成本計算與退回邏輯特徵測試（mock OpenAI client） |
| `test_summary.py` | 3 | 摘要產生的成本計算特徵測試（mock OpenAI client） |
| `test_openai_client.py` | 2 | `chat_completion_cost()` 成本計算公式 |
| `test_conversation.py` | 21 | 多輪對話 orchestrator：四種意圖的分支、搜尋範圍收窄的硬邊界、歷史摘要截斷 |
| `test_evaluation.py` | 23 | Golden Set 解析、`temporal_iou()`、Recall@K／MRR／nDCG@K／`is_hit()`／`predicted_answerable()` 等純評分邏輯 |

### 1.2 後端：db、services、api

| 測試檔案 | 測試數 | 涵蓋範圍 |
|---|---:|---|
| `test_db.py` | 47 | `init_db()` 建表冪等性、`mark_video_analyzed()` 的 COALESCE 語意、`reset_to_pending()`／`delete_video()` 級聯刪除、BM25 與 LIKE 檢索的範圍下推、CRUD round-trip |
| `test_job_manager.py` | 27 | 全專案唯一有 process 級共享狀態（分析 slot 旗標＋鎖）與 pump thread 的模組：queue 事件→jobs 欄位對映、**失敗路徑也要釋放 slot**、每個 job 各自的下載目錄、retry 狀態機 |
| `test_services_video.py` | 23 | 委派正確性、`store_upload()` 的 uuid4 檔名與不覆蓋既有上傳、縮圖與長度探測的失敗退回 |
| `test_services_conversation.py` | 5 | 對話狀態的 JSON 序列化 round-trip |
| `test_services_search.py` / `test_services_stats.py` | 3 | 薄包裝層的委派 |
| `tests/api/*.py` | 59 | FastAPI TestClient：六個 router 的狀態碼、錯誤 body 形狀、影片庫／待分析兩個清單的分界、文件端點 |
| `test_analyzer_integration.py` | 1 | `integration` marker，真的跑一次完整分析流程，約 US$0.002／次 |

### 1.3 前端 e2e（Playwright）

跑法與刻意不做的事見 [`README.md`](../README.md) 的「前端 e2e smoke」一節。要點：**不碰任何呼叫 OpenAI 的路徑**，資料由 `scripts/seed_smoke_db.py` 填進 `avs_test`（與 pytest 同一道 `_test` 結尾防護）。

| 測試檔案 | 檢查數 | 涵蓋範圍 |
|---|---:|---|
| `smoke.spec.ts` | 19 | 五個頁籤都掛得起來且無 console error、影片庫清單／分類 chips／庫內搜尋／狀態篩選／勾選搜尋範圍、待分析清單的分界、搜尋頁空狀態、頁籤 keep-alive、移除影片後 invalidation 有生效 |
| `library-panel.spec.ts` | 7 | 詳細面板：整理成文件（含失敗路徑）、重新分析、重新整理後接回進度、分析失敗影片的按鈕停用 |
| `analysis-tracking.spec.ts` | 3 | 送出分析後的完整狀態機、失敗路徑、重新整理後靠 active jobs 接回進度 |
| `youtube-card.spec.ts` | 3 | YouTube 結果卡片的下載狀態機與重複影片的錯誤訊息 |

後三個檔案用 `page.route()` 把後端回應攔下來：那些流程真的跑會呼叫 OpenAI 或打 YouTube，攔截之後不花錢、不出網路，但走的是元件真正的程式碼路徑，狀態轉換也由測試餵、不必等真的跑完。

**測試慣例**：`pyproject.toml` 設定 `addopts = "-m 'not integration'"`，一般 `uv run pytest` 不會意外花錢或因網路問題變得不穩定；要跑整合測試用 `uv run pytest -m integration`。純邏輯函式（不呼叫外部 API 的部分）一律拆成獨立函式方便直接單元測試，這是貫穿整個專案的設計原則，不是 08-19 之後才追加的慣例。

## 2. Golden Set

`docs/golden-set.csv`：**17 題**（13 題 `is_answerable=TRUE`、4 題 `is_answerable=FALSE`），涵蓋人物／物件／動作／語音／OCR／時序／多條件／無答案等查詢類型。曾經有 18 題，`gs-009` 因為資料矛盾已被刪除，定案為 17 題——**注意 `scripts/run_golden_set_eval.py` 的檔案開頭註解目前仍寫「對 18 題全部跑一輪」，是尚未同步的殘留文字**，見 [`05-known-limitations-and-open-items.md`](05-known-limitations-and-open-items.md)。

命中判定用「`video_id` 相同 且 時間區間有重疊（IoU > 0）」，不是精確比對單一時間區間，因為部分查詢（如 `gs-003`）同一題有多個正確答案區間。

## 3. Evaluator（`pipeline/evaluation.py`）

純邏輯評分函式（`temporal_iou`／`is_hit`／`recall_at_k`／`reciprocal_rank`／`ndcg_at_k`／`best_iou`／`f1_score`，皆不呼叫 API，可直接單元測試）與需要真實 `search()` 呼叫的整合函式（`evaluate_query`／`run_evaluation`）分離。指標：

- **Recall@1／Recall@5／MRR／nDCG@5**：只計算 `is_answerable=TRUE` 的題目（沒有正確答案的題目不適用「有沒有找到正確片段」）。
- **Mean Timestamp IoU**：僅命中題目計算，在候選結果中挑跟任一正確區間重疊最大的 IoU。
- **No-answer F1**：涵蓋全部題目，用 `SearchResponse.is_confident` 判斷預測是否可信，見 [`02-technical-decisions.md`](02-technical-decisions.md#無答案信心判斷)。

`nDCG@K` 假設每題概念上只有一個「正確答案」（IDCG 固定為命中發生在第一名的分數），不是多相關文件的一般化版本，這樣才能對齊 Recall／MRR「有沒有把答案排到前面」的量測目的。

**執行方式**：`uv run python scripts/run_golden_set_eval.py`（可加 `--top-k`），會呼叫真實 OpenAI API（翻譯＋embedding），費用是分毫等級，跟一般搜尋同量級；每次執行把結果存成 `docs/eval-runs/<timestamp>.json`，方便跨實驗比較。

## 4. Baseline 演進

| 版本 | Recall@1 | Recall@5 | MRR | nDCG@5 | Mean IoU | No-answer F1 |
|---|---:|---:|---:|---:|---:|---:|
| Dense-only baseline（V0，08-20 測） | 0.538 | 0.692 | 0.628 | 0.636 | 0.725 | 0.000 |
| Hybrid(Dense+BM25)+RRF（`RRF_K=5`） | 0.615 | 0.846 | 0.722 | 0.746 | 0.773 | 0.000（範圍外）|
| ＋無答案信心判斷（`is_confident`） | 0.615 | 0.846 | 0.722 | 0.746 | 0.773 | **0.667** |

**跑多次會有雜訊**：Recall@1／MRR／nDCG@5 在不同次執行之間會波動（`translate_query()` 這個 LLM 呼叫本身非決定性造成），Recall@5／Mean IoU／No-answer F1 在兩次執行間完全一致。比較實驗前後差異時，優先看後三者，Recall@1／MRR／nDCG@5 的單次差異不一定代表改動的效果。

## 5. 評測 baseline 的時效性警示

**上面整張表的 baseline 數字，都是在場景長度目標帶還是舊常數（`MERGE_BELOW_SEC=5.0`／`SPLIT_ABOVE_SEC=10.0`，6～12 秒目標）時測出來的。** 08-20 稍晚場景長度目標帶改成 8～12 秒（見 [`02-technical-decisions.md`](02-technical-decisions.md#場景長度正規化mergesplit含目標帶收窄的除錯過程)），但：

- `app.db` 既有已分析影片**還沒有**用新常數重新分析。
- `golden-set.csv` 的 `expected_start`／`expected_end` 時間戳**還沒有**針對新的片段邊界重新產生。

也就是說，只要 `app.db` 的影片或 golden set 沒有重新產生，上表數字仍然是有效、可重現的（因為片段邊界實際上還是舊的）；但**一旦重新分析影片套用新場景長度，這組數字就會失去比較基準，必須先重新產生 golden set 才能繼續用它評估之後的實驗**。這是目前最重要的一個「待確認事項」，詳見 [`05-known-limitations-and-open-items.md`](05-known-limitations-and-open-items.md)。

## 6. VLM 條件式多幀取樣上線後的驗證（只重跑 video 1）

見 [`02-technical-decisions.md`](02-technical-decisions.md#vlm-條件式多幀取樣)。只對 video 1 執行 `db.reset_to_pending()` ＋重新分析（真實 API 呼叫），其餘 6 支影片未變動，場景邊界（`start_sec`／`end_sec`）跟舊資料完全一致（PySceneDetect 邏輯沒變，只有 VLM 取樣幀數變了），所以只有 video 1 相關的兩題（gs-001／gs-002）指標可能變化，其餘 15 題理論上不受影響。

**費用**：$0.0907 → $0.1126（+24.2%）。`segment_count` 不變（58），`vlm_failed_count=0`，沒有觸發預算截斷。

**Golden set 全量重跑對照**（`docs/eval-runs/20260822_110013.json` vs 前一次 hybrid baseline）：

| 指標 | 條件式多幀前 | 條件式多幀後（只重跑 video 1） |
|---|---:|---:|
| Recall@1 | 0.538 | 0.462 |
| Recall@5 | 0.538 | 0.538 |
| MRR | 0.564 | 0.512 |
| nDCG@5 | 0.538 | 0.510 |
| Mean IoU | 0.717 | 0.797 |
| No-answer F1 | 0.667 | 0.667 |

**逐題變化**：
- **gs-001**（獨立評審名單 2019）：`recall_at_1` 從 `True` 退步成 `False`（`recall_at_5` 仍 `True`，`reciprocal_rank` 0.5）。原本單幀中點（5.6 秒）剛好拍到「30th ANNUAL INDEPENDENT CRITICS LIST」；video 1 開頭 0～44.8 秒本身也是快速疊圖轉場（`source_raw_duration=44.8` 觸發多幀），新版兩幀（3.36s／7.84s）拍到「TC Candler Presents」跟「100 Most Beautiful Faces of 2019」兩段不同文字，沒有拍到原本那句——這句文字改在影片結尾重複出現同樣品牌畫面的片段被找到，排名退到第 2。
- **gs-002**（Kate Beckinsale）：仍未修好，`recall_at_1`／`recall_at_5` 都還是 `False`。目標片段預期時間窗（108～113 秒）落在兩個切分後場景的探測幀縫隙間，2 幀固定比例取樣沒蓋到——但同一個場景確實新抓到之前完全看不到的另外兩張名卡（Kelly Gale、Mina Myoui），機制本身有效，只是這支影片的轉場密度對 2 幀來說仍然不夠。
- 其餘 15 題數字完全沒變（跟預期一致，這些題目對應的影片沒有重新分析）。

**結論**：這次改動不是單純的「涵蓋率變好」，而是「涵蓋範圍轉移」——新抓到了以前完全看不到的內容，但也因為取樣點改變，讓一個原本靠運氣矇對的案例排名退步。淨效果在這 18 題小樣本上是負的（Recall@1／MRR／nDCG@5 都下降），但樣本數太小（只有 2 題真正受影響），不足以下「這個功能整體上讓搜尋變差」的結論；比較有意義的解讀是「固定 2 幀、固定 30%/70% 比例的取樣密度，對這支影片的轉場密度不夠」，不是「訊號或機制本身無效」。
