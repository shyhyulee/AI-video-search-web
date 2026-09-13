# 測試與驗證

> **類型**：現況參考｜**狀態**：維護中，跟著程式碼更新
> 分類說明與完整索引見 [`README.md`](README.md)。

## 1. 測試套件現況

專案在 08-19 才第一次導入 `pytest`（本地 OCR 雙引擎 Phase 1 開發時），此後每個功能都同步補測試。目前有兩套：

- **後端 `pytest`：30 個檔案、471 個測試**，全部是不呼叫真實 API 的純邏輯／mock 測試（`uv run pytest` 預設執行），另有 1 個需要真實 API 的整合測試（`integration` marker，預設不執行）。
- **前端 Playwright e2e：7 個檔案、57 個檢查**（`cd frontend && npm run test:e2e`）。第四輪重構之前前端**一個測試都沒有**，見 [`01-development-timeline.md`](01-development-timeline.md) 的第四輪與第五輪重構。

> 下表的數字會隨開發變動，重點是**涵蓋範圍**而不是精確筆數。要現況數字跑
> `uv run pytest --collect-only -q`。

### 1.1 後端：pipeline

| 測試檔案 | 測試數 | 涵蓋範圍 |
|---|---:|---|
| `test_search.py` | 49 | `best_score()`／`select_relevant_ids()`／`extract_terms()`／`rrf_scores()`／`hit_source_label()`／否定句切分與排除，純向量與邏輯運算，不呼叫 API |
| `test_search_pipeline.py` | 20 | `search()` 端到端特徵測試：真實臨時資料庫，只把兩個 OpenAI 呼叫換掉，向量刻意用 4 維讓 cosine 值可人工推算 |
| `test_analyzer.py` | 34 | 本地 OCR 場景過濾、Phase C 平行 embedding 的 budget 截斷時機、Phase E／F 平行執行的失敗隔離與成本加總、Phase B 批次平行的場景順序保證與 rate limit 重試 |
| `test_media.py` | 21 | 五個 ffmpeg／ffprobe 呼叫端的命令列逐字鎖定、每一處都有 timeout、超時的失敗語意 |
| `test_ocr_service.py` | 15 | 文字正規化、場景內取樣邊界、事件去重合併 |
| `test_scene_detect.py` | 13 | merge/split 合併門檻邊界、結尾殘留片段處理、均分切割邊界對齊、無場景切換 fallback |
| `test_segment_material.py` | 27 | 摘要與文件共用的素材格式：欄位順序、`include_ocr` 開關、佔位字串過濾、時間戳 |
| `test_asr.py` | 10 | 幻覺字幕模式 A／B 的判斷邏輯（合成資料） |
| `test_document.py` | 21 | doc_type 判斷、片段數上限、prompt 組裝與成本計算 |
| `test_frame_qa.py` | 10 | 停格畫面問答：影格抽取、上下文串接、成本計算、影格取不到時的例外 |
| `test_intent.py` | 7 | 對話意圖判斷的 schema 解析與退回邏輯 |
| `test_vlm.py` | 6 | 畫面描述的成本計算特徵測試（mock OpenAI client＋`frames.extract_frame`） |
| `test_progress_estimation.py` | 5 | 共用的背景執行緒＋預估進度 helper（假 `work()` callable） |
| `test_ocr_adapters.py` | 4 | EasyOCR adapter 輸出轉換（假 reader 物件，不下載真實模型） |
| `test_translation.py` | 3 | 查詢翻譯的成本計算與退回邏輯特徵測試（mock OpenAI client） |
| `test_summary.py` | 3 | 摘要產生的成本計算特徵測試（mock OpenAI client） |
| `test_openai_client.py` | 10 | `chat_completion_cost()` 成本計算公式；`chat_prices()` 的模型單價表（唯一把公告價寫死在測試裡的地方，其餘成本測試都拿同一個常數算期望值） |
| `test_conversation.py` | 21 | 多輪對話 orchestrator：四種意圖的分支、搜尋範圍收窄的硬邊界、歷史摘要截斷 |
| `test_evaluation.py` | 23 | Golden Set 解析、`temporal_iou()`、Recall@K／MRR／nDCG@K／`is_hit()`／`predicted_answerable()` 等純評分邏輯 |

### 1.2 後端：db、services、api

| 測試檔案 | 測試數 | 涵蓋範圍 |
|---|---:|---|
| `test_db.py` | 49 | `init_db()` 建表冪等性、`mark_video_analyzed()` 的 COALESCE 語意、`reset_to_pending()`／`delete_video()` 級聯刪除、BM25 與 LIKE 檢索的範圍下推、CRUD round-trip |
| `test_job_manager.py` | 27 | 全專案唯一有 process 級共享狀態（分析 slot 旗標＋鎖）與 pump thread 的模組：queue 事件→jobs 欄位對映、**失敗路徑也要釋放 slot**、每個 job 各自的下載目錄、retry 狀態機 |
| `test_services_video.py` | 23 | 委派正確性、`store_upload()` 的 uuid4 檔名與不覆蓋既有上傳、縮圖與長度探測的失敗退回 |
| `test_services_conversation.py` | 5 | 對話狀態的 JSON 序列化 round-trip |
| `test_services_search.py` / `test_services_stats.py` | 3 | 薄包裝層的委派 |
| `tests/api/*.py` | 61 | FastAPI TestClient：六個 router 的狀態碼、錯誤 body 形狀、影片庫／待分析兩個清單的分界、文件端點 |
| `test_analyzer_integration.py` | 1 | `integration` marker，真的跑一次完整分析流程，約 US$0.002／次 |

### 1.3 前端 e2e（Playwright）

跑法與刻意不做的事見 [`README.md`](../README.md) 的「前端 e2e smoke」一節。要點：**不碰任何呼叫 OpenAI 的路徑**，資料由 `scripts/seed_smoke_db.py` 填進 `avs_test`（與 pytest 同一道 `_test` 結尾防護）。

| 測試檔案 | 檢查數 | 涵蓋範圍 |
|---|---:|---|
| `smoke.spec.ts` | 19 | 五個頁籤都掛得起來且無 console error、影片庫清單／分類 chips／庫內搜尋／狀態篩選／勾選搜尋範圍、待分析清單的分頁規則、搜尋頁空狀態、頁籤 keep-alive 保住 state |
| `library-panel.spec.ts` | 18 | 詳細面板：整理成文件（含失敗路徑）、重新分析、重新整理後接回進行中的工作、文件時間戳跳轉與觀看模式 |
| `conversation.spec.ts` | 6 | AI對話：一輪回完自動選第一名且**定格不播**、點卡片才播、空結果、搜尋範圍隨訊息帶上、停格問答的模式切換與上下文（時間點一變就清空） |
| `library-list.spec.ts` | 4 | 影片庫清單的排序：四個欄位、方向切換、與狀態篩選／庫內搜尋疊加 |
| `search-results.spec.ts` | 4 | 片段搜尋：搜完自動選第一名且定格、點結果才播、搜過沒找到的空狀態、搜尋範圍隨查詢帶上 |
| `analysis-tracking.spec.ts` | 3 | 送出分析後的完整狀態機、失敗路徑、重新整理後靠 active jobs 接回進度 |
| `youtube-card.spec.ts` | 3 | YouTube 結果卡片的下載狀態機與重複影片的錯誤訊息 |

除了 `smoke.spec.ts` 之外都用 `page.route()` 把後端回應攔下來：那些流程真的跑會呼叫 OpenAI 或打 YouTube，攔截之後不花錢、不出網路，但走的是元件真正的程式碼路徑，狀態轉換也由測試餵、不必等真的跑完。

**測試慣例**：`pyproject.toml` 設定 `addopts = "-m 'not integration'"`，一般 `uv run pytest` 不會意外花錢或因網路問題變得不穩定；要跑整合測試用 `uv run pytest -m integration`。純邏輯函式（不呼叫外部 API 的部分）一律拆成獨立函式方便直接單元測試，這是貫穿整個專案的設計原則，不是 08-19 之後才追加的慣例。

## 2. Golden Set

`docs/golden-set.csv`：**17 題**（13 題 `is_answerable=TRUE`、4 題 `is_answerable=FALSE`），涵蓋人物／物件／動作／語音／OCR／時序／多條件／無答案等查詢類型。曾經有 18 題，`gs-009` 因為資料矛盾已被刪除，定案為 17 題——**注意 `scripts/run_golden_set_eval.py` 的檔案開頭註解目前仍寫「對 18 題全部跑一輪」，是尚未同步的殘留文字**，見 [`04-known-limitations-and-open-items.md`](04-known-limitations-and-open-items.md)。

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

也就是說，只要 `app.db` 的影片或 golden set 沒有重新產生，上表數字仍然是有效、可重現的（因為片段邊界實際上還是舊的）；但**一旦重新分析影片套用新場景長度，這組數字就會失去比較基準，必須先重新產生 golden set 才能繼續用它評估之後的實驗**。這是目前最重要的一個「待確認事項」，詳見 [`04-known-limitations-and-open-items.md`](04-known-limitations-and-open-items.md)。

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

## 7. 畫面描述品質的量測

搜尋有 Golden Set 可以算 Recall@K／MRR，**畫面描述原本完全沒有量化方式**——只能人眼看，代表改 VLM prompt 沒有任何東西擋得住退步。2026-08-31 補上了。

### 7.1 工具

```bash
# 量現況（純讀資料庫，零 API 成本）
uv run python scripts/measure_description_quality.py
uv run python scripts/measure_description_quality.py --videos 4,28,32,34 --samples 5

# 比較多個 prompt 候選（唯讀不寫庫，會呼叫 API）
uv run python scripts/experiment_vlm_prompt.py --mode multi  --videos 32,34 --dry-run
uv run python scripts/experiment_vlm_prompt.py --mode single --videos 28,33,32 --limit 40
```

前者的結果寫成 `docs/eval-runs/desc-<timestamp>.json`，後者寫成 `desc-exp-<mode>-<timestamp>.json`，跟同資料夾的 Golden Set 搜尋評測結果用檔名前綴分開。

### 7.2 四個代理指標

| 指標 | 抓什麼 | 全庫 baseline（2026-08-31） |
|---|---|---|
| **籠統詞率** | 描述停在場景／氛圍層級（`顯示`／`正在`／`進行`／`設備`⋯） | 73.6% |
| **具體動作動詞率** | 能讓人重現動作的及物動詞（`搬`／`抬`／`插入`／`焊接`⋯） | 6.0% |
| **元描述率** | 在講幀之間的差異而不是內容（`第一張`／`逐漸變化`⋯） | 13.4% |
| **描述長度** | — | 平均 52.4 字 |

實驗腳本另有兩個欄位：**姿勢接觸率**（`彎腰`／`雙手`／`手持`⋯，因為刻意避開動作動詞的 prompt 會被具體動作率低估）與**人物提及率**（幻覺診斷用，見下）。

### 7.3 怎麼讀這些數字（三條，都是踩過才知道的）

1. **絕對值沒有意義，同一批片段的前後差值才有**。而且**雜訊比想像大**——同一個 prompt、同一組畫面重跑三次，籠統率範圍 5pt、具體動作 7.6pt、元描述 11.3pt。小於這個幅度的差異讀不出訊號。所以**對照組必須跟候選在同一輪執行**，不能拿資料庫既有描述來比。

2. **代理指標擋得住退步，擋不住幻覺**。多幀 prompt 的候選 B 三個指標全面勝出（具體動作 16.2%→47.5%、元描述 57.5%→7.5%），人眼抽看才發現它在 v32（純 3D 動畫、畫面裡沒有真人）**10/10 段**寫出「作業員」「技術人員」，還編出「用手擰緊固定螺絲」。**每輪實驗都要真的把描述印出來看。**

   實務做法：測試集裡固定放一支**已知畫面裡沒有人**的影片（目前用 v32）當幻覺對照組，它的人物提及率正確值是 0%，任何非零都是編造。

3. **元描述率把兩件事混在一起，而且拆開之後結論不變**。詞表裡的 `接著`／`隨著`／`逐漸` 會抓到「接著，作業員把晶圓放上平台」這種**正當的時序敘述**——那是多幀該有的產出，不是缺陷。2026-08-31 換成只抓「真的指涉圖片」的詞表（`第一張`／`畫面切換`／`隨著時間推移`…）重算過，aggregate 幾乎一樣（20.0% vs 22.0%），偽陽性與漏抓大致抵銷。**所以指標可以繼續用，但高元描述率要配合看樣本**：「只講畫面在變、沒有內容」跟「內容完整、順帶提一句切換」是兩回事，前者是缺陷，後者不是。

4. **籠統詞率對工廠類影片偏嚴，也對描述長度敏感**。詞表裡的 `設備`／`顯示`／`機器` 對半導體廠影片是正確用詞，一句同時講出「壓力計」（具體）與「設備」（籠統）也會被標記；描述變長之後句子變多，籠統詞的絕對命中數自然上升。**不適合單獨當驗收條件**，要跟具體動作率、姿勢接觸率與人眼抽看一起讀。

### 7.4 測試集怎麼挑

避開 `golden-set.csv` 引用的 **video 1／2／3／4**——重跑那幾支會讓搜尋 baseline 失去比較基準（見 §5）。目前用的四支：

| 影片 | 為什麼選它 |
|---|---|
| v28 Intel 工廠 | 真人產線，字幕只有 15%，最接近「無聲影片只靠影像判讀」 |
| v33 走進工廠：PCB | 真人產線，有中文旁白（對照組：字幕是有用的） |
| v32 螺桿滑台組裝 SOP | **純 3D 動畫、沒有真人** → 幻覺對照組 |
| v34 48 式太極 | 純動作內容，字幕對動作判讀沒有幫助 |
