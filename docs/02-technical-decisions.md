# 技術決策紀錄

依主題整理每個技術決策的背景、比較過的選項、實測數據與最終結論。時間順序見 [`01-development-timeline.md`](01-development-timeline.md)；已經嘗試但放棄的方案見 [`03-excluded-approaches.md`](03-excluded-approaches.md)。

## 基礎架構決策

- **Provider 只用 OpenAI（V0 起）**：ASR＝Whisper、VLM＝GPT-4o-mini、Embedding＝`text-embedding-3-small`。三個模組（`asr.py`／`vlm.py`／`embedding.py`）對外只暴露跟供應商無關的函式簽名，orchestrator（`analyzer.py`）不直接呼叫 OpenAI SDK，之後要加 Gemini 只需要在模組內部加分支。`segments` 表記錄每筆資料用哪個模型版本產生。
- **每支影片分析預算 US$0.20，只分析 20 分鐘以內的影片**：時長限制在 UI 層擋（`video_tab.py`），超過的影片不會呼叫 `start_analysis()`；預算是「跑到哪累加到哪」的即時金額，每處理完一個片段才檢查一次，超過就 `break`，已處理的片段不浪費。
  - **現況（原始決策的兩處已變更）**：預算調高到 **US$0.30**（VLM 條件式多幀取樣上線後，見本文件「VLM 條件式多幀取樣」）；長度上限 2026-08-26 放寬到 **1 小時**（`analyzer.MAX_DURATION_SEC`，見 [`11-web-ui-warm-redesign-plan.md`](11-web-ui-warm-redesign-plan.md) §8.11）。強制執行點也已從 UI 層搬到 API 層（`job_manager.submit_analysis()`，Tkinter 的 `video_tab.py` 已刪除）。**「跑到哪累加到哪」的預算機制本身沒變**——這正是為什麼放寬長度上限之後，60 分鐘的影片很可能先撞到 US$0.30 而變成部分完成。
- **場景切分選 PySceneDetect，不用固定間隔抽幀**：本機運算免費，且技術評估認為是低風險選項。
- **字幕／畫面描述／OCR 文字分開存、分開建 embedding**：不合併成一段文字只建一個向量——這是 `AI_Video_Search_搜尋準確率提升規劃.md` 明確要求的原則，V0 開始就遵守，之後所有搜尋相關改動都維持這個設計。

## 場景切分

### AV1 編碼影片場景切分失效

**現象**：`web_embedded` client 下載的 720p 影片常是 AV1 編碼，PySceneDetect 預設 `opencv` backend 沒有硬體加速時對 AV1 完全讀不到畫面（stats 檔案 0 筆資料）。
**影響**：整支影片被誤判成只有 1 個場景，不是真的偵測不到切換，而是根本沒讀到畫面。
**原因**：`opencv` backend 軟體解碼路徑不支援這台機器的 AV1 解碼。
**解決方案**：用 `ffprobe` 先偵測影片編碼，AV1 才切換成 `pyav` backend（新增依賴 `av`，用 ffmpeg 自己的解碼器）。
**驗證結果**：602 秒影片原本誤判成 1 個場景，修正後正確找到 19 個；`pyav` backend 較慢（實測需 79～85 秒，`opencv` backend 約 19 秒）。
**目前狀態**：已實作（`scene_detect._is_av1()`）。**已知缺口**：`_is_av1()` 對 `subprocess.SubprocessError`／`OSError` 是靜默吞掉（連 log 都沒有），失敗時悄悄退回 `opencv` backend，除錯時不容易發現，這是已知但優先度低的小缺口。

### 多 Detector 聯集（`ContentDetector` + `AdaptiveDetector`）

**現象**：`ContentDetector` 單獨使用會漏掉漸進式轉場（溶接／crossfade）——實測用「The 100 Most Beautiful Faces of 2019.mp4」前 3 分鐘比對，把 45.88～180.01 秒（134 秒）判成單一場景，但這段其實有至少 5 個不同人物條目。
**原因**：查證 PySceneDetect 原始碼確認 `SceneManager._process_frame()` 的多 detector 合併邏輯是**聯集（OR）**，不是加權投票——只要「任一個」detector 判定切，這一幀就會被加進切點清單。
**解決方案**：`SceneManager.add_detector()` 掛上 `ContentDetector()` 與 `AdaptiveDetector()` 兩個 detector（原本用的是只吃單一 detector 的 `scenedetect.detect()` convenience function，改用底層 `SceneManager` API）。
**驗證結果**：602 秒影片場景數從 19 增加到 33，耗時幾乎沒差（88.5s vs 校準值約 85s，不需要重新校準進度估算比例）；抽幀肉眼比對確認新抓到的切點皆為真實場景轉換。曾評估加 `ThresholdDetector`，因 false positive 風險偏高不採用，見 [`03-excluded-approaches.md`](03-excluded-approaches.md)。
**目前狀態**：已實作（`scene_detect._build_detectors()`）。因為是聯集關係，加更多 detector 只會讓場景更碎，不會讓長度更接近目標——長度目標完全靠下面的 merge/split 後處理達成，是跟長度正規化互補、不是取代的關係。

### 場景長度正規化（merge/split），含目標帶收窄的除錯過程

**背景**：PySceneDetect 原始輸出長度落差極大（同一支影片 0.10 秒到 129.76 秒都有），VLM／本地 OCR 只在片段中間取樣，太短的片段沒有代表性、太長的片段可能漏看內容。

**演算法**：兩個 pass 套用在偵測結果之後——Pass 1（`_merge_short_scenes`）由左到右累積場景，達到 `MERGE_BELOW_SEC` 就提交；Pass 2（`_split_long_scenes`）長度超過 `SPLIT_ABOVE_SEC` 的場景，依 `SPLIT_TARGET_SEC` 均分成 n 段。**順序刻意是 merge 先、split 後**：如果 split 先做，merge 可能把切好的片段黏回去、又超過長度上限；merge 先、split 當最後一道保險，確保輸出長度上限有保證。

**第一版常數（08-19）**：`MERGE_BELOW_SEC=5.0`／`SPLIT_ABOVE_SEC=10.0`／`SPLIT_TARGET_SEC=9.0`（6～12 秒目標帶）。真實影片驗證：33 個原始場景 → merge 後 21 個 → split 後 69 個，**96%（66/69）落在 6～12 秒範圍**，其餘 3 個只是略低於 6 秒（5.24～5.54 秒），沒有超過 12 秒的。

**目標帶收窄除錯過程（08-20）**：使用者希望片段更完整，改成 9～12 秒（`MERGE_BELOW_SEC=9.0`／`SPLIT_ABOVE_SEC=12.0`／`SPLIT_TARGET_SEC=10.5`）。

- **現象**：命中率不升反降——BMW 工廠影片只有 67.7%（63/93）落在目標帶內，另一支影片 91.1%（51/56），比原本 96% 低很多。
- **原因**：`_split_long_scenes()` 原本有「至少切 2 段」的邏輯（`max(2, round(length/target))`），只有當 `SPLIT_ABOVE_SEC ≥ 2 × MERGE_BELOW_SEC` 時，切 2 段才保證兩段都不低於下限。舊常數剛好滿足 `12 = 2 × 6`，這正是 96% 命中率的真正原因，不是巧合。9～12 秒不滿足這個關係（`12 ≠ 2 × 9 = 18`），任何原始場景落在 **12～18 秒**（下限的 2 倍）這個「切了會低於下限、不切又超過上限」的死區，都只能二選一，且原本的「至少切 2 段」邏輯在窄帶下會強制違反下限（例如 12.1 秒被切成 2 段、每段只有 6.05 秒）。
- **解決方案**：`piece_count` 改成從 `round(length/target)` 開始，用 while 迴圈往下修正到每段都 `≥ MERGE_BELOW_SEC` 為止，辦不到就保留單一超長片段——**寧可片段偶爾超過上限，也不要低於下限**（下限存在的目的是避免 VLM／OCR 只看到一小段畫面，比片段稍微超長更傷）。同時把目標帶改成 **8～12 秒**（`MERGE_BELOW_SEC=8.0`／`SPLIT_ABOVE_SEC=12.0`／`SPLIT_TARGET_SEC=10.0`，`8 = 12/1.5`，死區縮小到 12～16 秒）。
- **驗證結果**：兩支測試影片命中率回升到 78.8%（82/104）與 91.4%（53/58），下限保證兩支都是 100% 沒違反（min 8.01／8.64 秒），最長片段也縮短（14.95／15.95 秒）。
- **目前狀態**：**已定案 `MERGE_BELOW_SEC=8.0`／`SPLIT_ABOVE_SEC=12.0`／`SPLIT_TARGET_SEC=10.0`**，這是目前程式碼（`scene_detect.py`）的實際常數。還沒到 6～12 秒的 96% 水準（那是死區完全消失的特例），但比 9～12 秒版本更接近目標、且完整保留下限保證。
- **下一步**：`app.db` 既有影片要重新分析才會套用新切分（會產生 API 費用，待決定）；`golden-set.csv` 的 `expected_start`／`expected_end` 需要重新產生，舊的搜尋準確率 baseline 在片段邊界改變後可能已經失去比較基準，詳見 [`04-testing-and-evaluation.md`](04-testing-and-evaluation.md#5-評測-baseline-的時效性警示)。

**已知限制**：「死區」（`SPLIT_ABOVE_SEC` ~ `2×MERGE_BELOW_SEC` 之間）造成的超長片段沒有絕對上限保證——理論上一個原始場景剛好落在死區內、且前後都無法被 merge pass 吸收，會直接保留原始長度。只在 2 支影片（BMW 工廠、Faces 2019）驗證過，命中率落差顯示強烈依賴內容剪輯節奏，沒測過球賽轉播、教學影片等其他類型的分佈。

## ASR：Whisper 幻覺字幕過濾

**背景**：`asr.py` 保留 Whisper 原生回傳的 `no_speech_prob`／`avg_logprob`／`compression_ratio` 三個信心分數，但 08-18 上線時只做擷取儲存，沒有過濾邏輯。查真實 `app.db`（6 支已分析影片、560 筆片段）發現**兩種完全不同的幻覺模式**，需要兩套獨立偵測邏輯。

### 模式 A：`no_speech_prob` 偏高卻仍生成文字

**現象**：背景音樂被誤判成重複亂碼（例如柬埔寨文亂碼字串），橫跨數百秒。
**訊號**：真實對白影片的 `no_speech_prob` 最高值只有 0.264～0.487，幻覺片段集中在 0.7～0.985，中間有明顯空隙。
**解決方案**：`asr.is_hallucinated_transcript()`，門檻 `NO_SPEECH_PROB_THRESHOLD=0.7`，命中就不建立字幕 embedding（`segments.transcript` 仍照實際內容寫入，只是不能被搜尋到）。
**已知缺口**：對模式 B 完全沒有效果。

### 模式 B：信心分數正常，但文字是單字重複

**現象**：BMW 工廠紀錄片 141 筆非空字幕**全部**是「Music」／「Music Music」，但三個信心分數的範圍全部跟真實對白重疊（`no_speech_prob` 0.094～0.861、`avg_logprob` -1.812～-0.078、`compression_ratio` 0.385～1.706），模式 A 只抓到 7/141 筆，沒有任何簡單數值門檻能分離。

**探索過程，兩個天真做法都會誤殺真實內容**：

1. 「連續場景主導詞相同」單獨使用：英文長句的 `the` 本來就常是最高頻詞，會誤殺 NBA 真實對白。
2. 「單一場景內主導詞佔比」單獨使用：中文動物教學短促內容的佔比比真正在幻覺的影片還高，會把整支教學影片洗掉。

**解決方案**：兩個條件都成立、且連續發生——該場景主導詞佔比 `≥ 0.5`（`DOMINANCE_RATIO_THRESHOLD`）**且**跟前一場景主導詞相同，連續達到 `MIN_REPETITION_RUN_LENGTH=3` 個場景以上。門檻用真實資料的空隙選出（真實內容最長連續只到 2，幻覺案例最低是 4）。`asr.find_repetitive_transcript_indices()` 跨場景掃描整支影片字幕，在 `_run_embedding_phase()` 迴圈開始前算一次。

**驗證結果**：真實內容（NBA、動物教學）0 誤殺；4 支已知幻覺影片各抓到 41／141／4／33 筆，其中 BMW 工廠（video=4）從模式 A 只抓 7/141 提升到模式 B 全數 141/141。

**已知、刻意接受的邊界情況**：如果未來影片真的有「連續 3 次以上喊同一句口號／副歌」的真實內容，也會被一起過濾——判斷這種情況下被過濾不算太糟（重複口號本來就不是有搜尋價值的內容），是刻意接受的取捨，不是要修的 bug。

## VLM 與 OCR

### VLM-OCR：同一次呼叫取得畫面描述與畫面文字

**決策**：用 OpenAI structured output（`chat.completions.parse` + Pydantic model `_SceneAnalysis{description, on_screen_text}`）讓 GPT-4o-mini 在同一次呼叫裡回傳畫面描述與畫面上的文字，不用傳統 OCR 引擎（PaddleOCR／Tesseract），也不用額外 API 呼叫，成本幾乎不變。
**驗證**：用燒錄文字的測試影片驗證 `description`／`ocr_text` 正確分離，文字逐字精準擷取。
**限制**：只看場景「中點」那一張畫面，中點以外時間點才出現的文字會漏掉——這是本地 OCR（下方）存在的理由。

### 本地 OCR 雙引擎（EasyOCR，Phase 1）

**與原始需求的差異**：原始需求（`Claude_Code_OCR_影片搜尋開發規劃.md`）假設 OCR 完全還沒做，要求本地開源雙引擎（EasyOCR＋Tesseract）取代雲端方案。但 VLM-OCR 已經先上線。使用者拍板：**VLM-OCR 保留不動，本地雙引擎定位成互補**——VLM 只在場景中點抽一張畫面，本地引擎在同一場景內多看幾張畫面，抓 VLM 抽幀方式漏掉的文字，不是取代或比賽準確度。

**資料模型**：獨立 `ocr_events` 表（`video_id`／`segment_id`／時間範圍／`raw_text`／`resolved_text`／`confidence`／`bbox`／`primary_engine`／`embedding`），Phase 1 只做精簡欄位，原始需求要求的 `quality_status`／`resolution_method`／`preprocessing_profile`／多引擎候選 JSON 留到 Phase 2 真的有雙引擎融合時再加。

**取樣策略的除錯過程**：

1. **第一版**：依序掃描全部場景，每場景抽滿 `MAX_FRAMES_PER_SCENE` 張才換下一個場景，時間預算用完就停（`TIME_BUDGET_SEC=60`）。
2. **現象**：用真實已分析影片（69～160 場景）校準，發現 EasyOCR 在這台機器上 CPU-only、每張畫面約 4.7 秒，60 秒預算依序掃描只能掃到最前面 3～4 個場景。
3. **第一次修正**：改成只掃描 VLM-OCR 沒抓到文字的場景（缺口場景）——多數影片 VLM 已覆蓋 98～100%，缺口很小，60 秒綽綽有餘。但 VLM 覆蓋率低的內容（例如體育賽事，一支 NBA 影片缺口達 52/108 場景）仍然不夠，因為舊版邏輯還是依場景順序、每個場景先抽完全部張數才換下一個，60～68 秒預算內只掃得到最前面 5 個缺口場景。
4. **第二次修正（回合制廣度優先）**：改成第 1 輪讓每個缺口場景先各拿 1 張畫面，全部場景輪過一次才進第 2 輪回頭補第 2 張，時間預算逐張畫面檢查（不是逐場景或逐輪次）就中止。
5. **驗證結果**：同一支 NBA 影片場景覆蓋數從 5/52 提升到 18/52，耗時從 68.1 秒降到 61.3 秒。

**已實測並放棄同一輪內用執行緒平行處理抽幀＋辨識**，見 [`03-excluded-approaches.md`](03-excluded-approaches.md)。

**目前狀態**：Phase 1（EasyOCR MVP）已完成。Phase 2（Tesseract 條件式複核）、Phase 3（獨立 exact/BM25 OCR 檢索通道）尚未開始，詳見 [`05-known-limitations-and-open-items.md`](05-known-limitations-and-open-items.md)。

### VLM 條件式多幀取樣

**動機**：VLM 畫面描述只在場景中點抽一張畫面（見上）——golden set gs-002（Kate Beckinsale）miss 追查發現，這不只是「中點以外的文字漏掉」的 OCR 問題，連畫面描述本身也會漏掉整段內容：video 1（The 100 Most Beautiful Faces of 2019）98.6～109.0 秒這個場景，實際塞了至少 4 張快速切換的排行榜名卡，但單張中點畫面只拍到其中一張，`ocr_events`／`segments` 兩張表都完全查不到「BECKINSALE」文字。

**已排除的兩版本地訊號**（純 pixel/色彩差異，探測幀取樣＋HSV 差異比對）完整實測記錄見 [`03-excluded-approaches.md`](03-excluded-approaches.md#vlm-多幀觸發pixelhsv-差異偵測)——兩版都無法把已知案例（segment 1346）跟正常場景分開，鏡頭運動／人物動作的視覺活動量遠蓋過「內容主體真的換了」這個訊號。

**真正根因與採用的訊號**：對 video 1 跑一次真正的 PySceneDetect 原始偵測（未合併／未切分）發現 67.37～140.31 秒（72.94 秒）整段被判成「一個」原始場景，完全沒有偵測到任何切點——segment 1346 是這個超長原始場景被 `_split_long_scenes()` 均分出來的第 4/7 段。改用「這個最終場景是不是從超長原始場景硬切出來的」當觸發訊號：這個資訊 Phase A 場景切分本來就會算出來（`_split_long_scenes()` 內部已知每段的來源長度），只是正式程式碼目前算完就丟，改用它幾乎零額外成本，不用像 pixel-diff 版本那樣另外跑 ffmpeg 抽幀＋cv2 比對。

**全 corpus 校準結果**（7 支影片、537 個既有場景，重跑一次原始場景偵測純本地驗證，不呼叫任何 API）：觸發率明顯分成兩群——

| 影片類型 | 支數 | 場景數 | 觸發數 | 觸發率 |
|---|---:|---:|---:|---:|
| Most Beautiful Faces 系列（溶接式排行榜） | 3 | 185 | 173 | 93.5% |
| 其他（NBA／BMW／動物／棒球，連續動作為主） | 4 | 352 | 65 | 18.5% |

門檻定案 **`source_raw_duration > 20.0` 秒**（`source_raw_duration` 是這個最終場景所屬、合併後切分前的原始場景長度；`source_raw_duration <= SPLIT_ABOVE_SEC=12.0` 的場景不會被切分，恆不觸發）。測過 12s／20s 兩個門檻：20s 對「正常」四支影片有實質過濾效果（觸發率 18.5%→7.7%），對溶接式排行榜三支幾乎沒差（93.5%→88.1%），因為它們的原始場景長度本來就遠超過 20 秒（最長一段 253.1 秒）。

**費用影響**：實測同一場景（segment 1346）3 幀 VLM 呼叫費用是單幀的 2.81 倍（prompt tokens 2960→8700，completion tokens 77→122）。用真實 7 支影片費用反推，20s 門檻下全 corpus 費用預期漲 **+20.6%**（$0.82→$0.99，7 支影片總和）。其中 video 6（Most Beautiful Faces 2021，觸發率 95.3%）換算後單支費用約 $0.2015，超過原本 `BUDGET_USD=$0.20`。

**決策**：門檻定案 20 秒；觸發後取 **2 幀**（片段 30%／70% 時間點，不是中點單幀）；`BUDGET_USD` 調高到 **$0.30**；`VLM_BATCH_SIZE` 從 5 降到 **3**（見下方「實作」）。

**實作**：`scene_detect.NormalizedScene`（取代原本的 `tuple[float, float]`）帶上 `source_raw_duration`；`pipeline/analyzer.py` 新增 `MULTI_FRAME_TRIGGER_SEC=20.0`／`MULTI_FRAME_FRACTIONS=(0.3, 0.7)`／`_frame_fractions_for()`，Phase B 依此決定每個場景要傳給 `vlm.describe_segment()` 幾個時間點；`vlm.describe_segment()` 新增 `frame_fractions` 參數（預設 `(0.5,)`，向後相容），多幀時用獨立的 prompt 模板（要求 VLM 綜合所有畫面、不要逐張重複描述）；`segments` 表新增 `vlm_frame_count` 欄位記錄每個片段實際用了幾張畫面。

`VLM_BATCH_SIZE` 從 5 降到 3：回頭用 `tiktoken` 驗證原本 5 的推導依據時發現，原始估算假設「low」解析度圖片固定 85 tokens（一般 gpt-4o 的公式），但實測 gpt-4o-mini 單幀呼叫真實 prompt tokens 是 2960（圖片本身就佔約 2880 tokens），比原估計高了一個數量級；這個落差過去沒有造成實際問題（0 次撞 rate limit），研判是真實 API 呼叫延遲本身就有節流效果，不是 token 預算公式在把關。條件式多幀上線後觸發場景的 call 用量再乘上約 1.9 倍，沒有足夠把握重新推導精確數字，保守把批次大小降到 3，見下方驗證結果。

**驗證結果**（只重新分析 video 1，真實 API 呼叫，見 [`04-testing-and-evaluation.md`](04-testing-and-evaluation.md#6-vlm-條件式多幀取樣上線後的驗證只重跑-video-1)）：費用從 $0.0907 漲到 $0.1126（+24.2%，比校準時抓的 +20.6%~57.9% 估計區間更低，因為實際採用 2 幀不是校準時參照的 3 幀，倍率更小）；58 個場景全部處理完、沒有觸發預算截斷、0 個 VLM 失敗。

**已知限制（更新）**：
- **多幀取樣不是單純疊加涵蓋率，是「轉移」涵蓋範圍，可能讓原本矇對的案例變成沒矇到**：gs-001（獨立評審名單 2019）原本每次都命中 recall@1，這次退步成 recall@1=False（仍在 recall@5 內，reciprocal_rank 0.5）。根因：video 1 開頭 0～44.8 秒也是同一種快速疊圖轉場（`source_raw_duration=44.8` 觸發多幀），舊版單幀中點（5.6 秒）剛好拍到「30th ANNUAL INDEPENDENT CRITICS LIST」字樣，新版兩幀（3.36s／7.84s）拍到的是另外兩段不同文字（「TC Candler Presents」「100 Most Beautiful Faces of 2019」），這段文字這次完全沒被任何一幀拍到，直到影片結尾重複出現同樣品牌畫面的片段才被找到（排名因此退到第 2 名）。
- gs-002（Kate Beckinsale）**仍未修好**：目標片段預期時間窗（108～113 秒）剛好落在兩個切分後場景（98.6～109.0、109.0～119.5）的探測幀之間的縫隙（探測幀落在 101.7／105.9／112.2／116.4 秒），2 幀固定比例取樣沒有蓋到那個窗口——但同一個場景確實新抓到了之前完全看不到的另外兩張名卡（Kelly Gale、Mina Myoui），驗證了訊號跟機制本身是有效的，只是固定 2 幀的取樣密度對這支影片的轉場密度來說仍然不夠。
- 上面兩點都只在 video 1 一支影片驗證過；其餘 6 支（尤其觸發率低很多的 NBA／BMW）沒有實測驗證會不會有類似的「取代而非疊加」副作用。
- 2.81 倍（多幀費用倍率，3 幀時測的）／32%（VLM 佔總花費比例）這兩個假設只在 video 1 單一場景測過，全 corpus 的費用估計是推算值；2 幀的真實倍率比 3 幀低，實測 video 1 是 +24.2%。
- `VLM_BATCH_SIZE=3` 降到目前這個值是保守調整，不是精確推導出的數字，實際會不會撞 429 只驗證過 video 1 這次重新分析（0 次撞 rate limit，但只有 58 個場景、其中約 85% 觸發多幀，跟其他影片的觸發率分布不同）。
- 這個訊號只解決「場景切分完全沒偵測到切點」這一種漏拍模式，不處理「有偵測到切點但單幀畫面描述本身品質不夠」這類其他可能的漏拍原因。
- 其餘 6 支影片還沒用新邏輯重新分析（會產生 API 費用，也會讓現有 golden set baseline 失去比較基準，見 [`04-testing-and-evaluation.md`](04-testing-and-evaluation.md#5-評測-baseline-的時效性警示)）。

## Embedding：統一 1024 維

`text-embedding-3-small` 原生輸出 1536 維，用 API 的 `dimensions` 參數截短到 **1024 維**（模型訓練時就支援這種截短，品質損失很小），統一 transcript／visual／ocr 三種 embedding 欄位的維度。同一批可比較的向量必須來自同一個模型，不同 embedding 模型的向量空間不可混用比較。

## 搜尋

### 雙語查詢翻譯

**背景**：實測 `text-embedding-3-small` 對 5 組跟專案內容相關的中英文同義配對，cosine 相似度平均 0.6538，跟不相關語句對照組平均 0.1098 有明顯差距——確認 embedding 模型本身就有跨語言對齊能力，這個功能是「提升排序品質」，不是修復完全搜不到的問題。
**決策**：查詢先用 GPT-4o-mini structured output 翻譯成中英文兩個版本（原始查詢字串也保留在候選集合裡），每個模態的分數對這些查詢向量取最高分（`_best_score()`）。翻譯失敗優雅退回只用原始查詢。
**依使用者指示**：只做中文／英文兩種語言，不做成通用多語言字典。
**驗證**：英文畫面描述 vs 中文查詢「警告標誌」，分數從 0.5624（不翻譯）提升到 0.6704（翻譯後）。

### 影片層級篩選

**背景**：全域搜尋（沒指定 `video_id`）先依影片摘要（無摘要退回標題）判斷查詢跟哪些影片相關，只在相關影片的片段內比對，減少不相關影片的雜訊。`_relevant_video_ids()` 用兩層安全網：最高分低於 `MIN_RELEVANCE` 代表沒有影片明顯相關（不篩選）；否則只留下跟最高分差距在 `RELEVANCE_MARGIN` 以內的影片。

**現象**：一開始沿用短標題實測估出的 `MIN_RELEVANCE=0.25`，但用貼近真實情境的長摘要測試「Keira Knightley」查詢，最高分只有 0.22，被誤判成「沒有明顯相關影片」而沒有篩選。
**原因**：長摘要因為內容更發散，就算是明確相關的查詢，峰值相似度也會系統性偏低，跟短標題時期估的門檻不適用。
**解決方案**：改成以**相對差距**（`RELEVANCE_MARGIN=0.15`）為主要判斷依據，`MIN_RELEVANCE` 降到 **0.10** 只當基本下限。
**驗證結果**：5 組查詢（動物／Keira Knightley／2019年最美麗的臉／警告標誌／貓咪）全部正確收斂到對應的單一支影片。
**已知限制**：只用兩支真實影片、幾組查詢實測驗證過，不是嚴謹調校的結果；影片數變多、摘要風格差異變大時可能需要重新校準。標題／摘要的 embedding 用記憶體快取（`_embed_cached()`，不寫回 DB，重啟清空），同一段文字同一次 app 執行期間只會真的呼叫一次 API。

### Hybrid 檢索與 RRF 融合

**背景**：純 dense cosine 排序無法把 answerable／no-answer 兩組查詢分開（golden set 實測 no-answer 題目 top1 相似度落在 0.41～0.74，跟 answerable 題目重疊），也有 hard negative 誤判（例如「汽車」dense 完全沒排進正確的影片）。

**技術背景（已查證）**：SQLite 內建 FTS5，不用裝新套件。FTS5 預設的 `unicode61` tokenizer 對中文完全無法比對子字串（中文沒有空白分詞），改用 `tokenize='trigram'` 才能正確比對中文子字串——代價是**查詢字串小於 3 個字元完全查不到任何結果**（不是分數低，是 tokenizer 產生不出 trigram），這對中文殺傷力很大（「汽車」「獅子」這類雙字詞剛好卡在這條線下面）。

> **2026-08 更新（遷移到 PostgreSQL 之後）**：上面這段的**結論仍然成立、實作換掉了**。
> PostgreSQL 的 `to_tsvector` 對中文有一樣的斷詞問題（`simple` parser 會把整句當成一個
> token），所以同樣選 trigram 路線——改用 `pg_trgm` 的 GIN 索引，BM25 分數在 SQL 裡自己算
> （PG 沒有等價內建函式，`ts_rank` 只吃 tsvector）。「選 trigram 而不是內建全文檢索」這個
> **決策本身沒有變**，只是換了一套 trigram 實作。
>
> 有一項限制消失了：`pg_trgm` 對 <3 字元的詞**查得到**，只是用不到索引加速（走 seq scan）。
> 但 `sparse.py` 的短詞 fallback 與哨兵分數**刻意沒有跟著簡化**——那會變成搜尋排名的行為
> 變更，讓遷移的 golden set 差異無法歸因。這個已知落差記在
> `tests/test_db.py::test_fts_bm25_search_short_query_now_finds_results`，
> 細節見 [`14-postgresql-migration-plan.md`](14-postgresql-migration-plan.md) §5.2.1。

**斷詞方式**：不引入 jieba，用純規則（正則抽英文／數字 token；中文用手刻的虛詞表切開字串，剩下連續片段當一個候選詞）。`≥3` 字元的詞用 FTS5 `bm25()`（真正的 IDF 加權）；`<3` 字元的詞用 LIKE fallback，找到就給一個排在所有真正 bm25 分數之前的哨兵分數（模擬「精確關鍵字命中應該最優先」）。詳見 [`03-excluded-approaches.md`](03-excluded-approaches.md#搜尋不引入-jieba-斷詞)。

**融合方式**：RRF（Reciprocal Rank Fusion）：`score = Σ 1/(k + rank)`，dense 排名（涵蓋全部候選片段）與 sparse 排名（BM25/LIKE 找到的片段）各自算一次再相加，沒被某個 channel 找到的片段，該 channel 貢獻是 0，不是懲罰分數。

**`RRF_K` 調參**：業界慣例值是 60，但實測候選片段多（一兩百個）時會讓「兩個 channel 都中等」贏過「單一 channel 命中得很準」。掃過 60/20/10/5 四個值，隨 k 變小持續單調變好，Recall@1 0.538→0.615、Recall@5 0.692→0.846、MRR 0.628→0.722、nDCG@5 0.636→0.746、Mean IoU 0.725→0.773，全部超過 baseline。使用者在單調改善持續四個點之後主動決定停在 **`RRF_K=5`**（不是遇到反例或效能瓶頸才停），還沒掃過更小的 k（例如 1、2）會不會出現反轉或不穩定，是現成的下一步。

**UI 透明度問題**：排序依 RRF 融合分數，畫面上「相似度」欄位只顯示 dense cosine 分數，兩者刻意分開（RRF 不覆寫 `similarity` 欄位）。使用者發現排名沒有依相似度欄位排序而追查，確認是設計如此後，新增 `SearchResult.fusion_score` 欄位跟 UI「融合分數」欄位，讓兩個數字並列可見，避免誤讀。

**已知限制**：只在 17 題小樣本驗證；虛詞表是針對這批 golden set 手動調的；`RRF_K=5` 只掃過 4 個點就定案。

### 無答案信心判斷

**背景**：`evaluation.py` 原本用 `predicted_answerable()` 借用 `search.MIN_RELEVANCE`（0.10）當門檻，但這個門檻是設計給「影片層級」預篩用的，套在「片段層級」的 top1 dense 相似度上不成立，golden set 4 題無答案查詢 top1 相似度實測 0.41～0.74，導致 `no_answer_f1` 恆為 0。

**訊號探索**（對 17 題印出四個候選訊號，比較 answerable 組與 no_answer 組的分佈範圍）：

| 訊號 | answerable 組範圍 | no_answer 組範圍 | 分不分得開 |
|---|---|---|---|
| top1 dense 相似度 | 0.463～1.000 | 0.411～0.744 | 否，重疊嚴重 |
| top1 RRF 融合分數 | 0.1667～0.3333 | 0.1667～0.2083 | 否，下緣完全重疊 |
| top1/top2 分數差距 | 0.0017～0.1905 | 0.0046～0.0238 | 否，重疊嚴重 |
| **top1 是否被 sparse 印證** | 11/13 為 True | 1/4 為 True | **是，乾淨分開** |

**解決方案**：`_rrf_scores()` 額外回傳「有被 sparse channel 找到的 segment id 集合」，`SearchResponse.is_confident` 判斷 top1 是否在這個集合裡。`evaluation.predicted_answerable()` 直接讀 `response.is_confident`。

**驗證結果**：`no_answer_f1` 從 0.000 提升到 **0.667**（precision 0.600、recall 0.750），Recall@5（0.846）／Mean Timestamp IoU（0.773）完全沒變，是預期結果——`is_confident` 不影響排序邏輯，只是額外算一個訊號。

**已知限制**：**無法處理否定句**（例如「工廠裡沒有機器人」，BM25 照樣命中「機器人」字面關鍵字，這是語意理解問題不是門檻問題）；只在 17 題（4 題無答案）小樣本驗證，無答案樣本數特別少，統計力弱；依賴 `_extract_terms()` 能拆出至少一個候選詞，查詢全部由虛詞組成會恆為 False。

**跑兩次確認的雜訊**：Recall@1／MRR／nDCG@5 在兩次執行之間會波動（例如 Recall@1 一次 0.692、一次 0.615），判斷是 `translate_query()`（LLM 呼叫）本身的非決定性造成，No-answer F1／Recall@5／Mean IoU 兩次完全一致。比較這幾個指標時要留意這個雜訊。

### Sparse Channel 短詞哨兵分數修正（避免泛用詞稀釋精確關鍵字）

**背景**：`_sparse_scores()` 對 <3 字元的關鍵字用 LIKE fallback，命中就給一個極端哨兵分數 `_SHORT_TERM_SPARSE_SCORE = -1e6`，讓它排在所有真正 bm25 分數之前（模擬「精確關鍵字命中應該最優先」，見上方「Hybrid 檢索與 RRF 融合」）。

**現象**：對話搜尋實測發現查詢「找出全壘打的畫面」跟單純查「全壘打」，結果不一樣。`_extract_terms()` 把前者拆成 `["全壘打", "畫面"]`——「全壘打」在 `app.db` 只命中 10 個片段（真實 bm25），但「畫面」是泛用描述詞，命中 527 個片段（全庫 681 個片段的 77%）。原本的邏輯是短詞哨兵分數無條件覆寫（`min(scores.get(seg_id, 0.0), _SHORT_TERM_SPARSE_SCORE)`），這 527 個只是剛好提到「畫面」、跟查詢語意無關的片段全部並列在哨兵分數，把真正命中「全壘打」的 10 個片段擠到排名後面。

**解決方案**：兩層修正（`search.py::_sparse_scores()`）：
1. 短詞哨兵分數改用 `scores.setdefault(...)`，只補「完全沒被任何長詞 bm25 找到」的片段，不覆寫已經算出來的真實 bm25 分數。
2. 新增 `_SHORT_TERM_MAX_MATCH_RATIO = 0.2`：短詞如果命中超過候選片段池 20% 的比例，視為沒有鑑別力的泛用詞，整個跳過、不當 sparse 訊號。第一層修正單獨實測發現不夠——因為排序看的是名次，就算「全壘打」保住自己的真實分數，其餘 522 個不相關的「畫面」片段還是會用哨兵分數並列霸佔最前面名次，一定要兩層一起才能解決。

**驗證結果**：用真實 `app.db` 比對，兩個查詢（「找出全壘打的畫面」／「全壘打」）的 sparse channel 排序結果變成逐筆完全相同。新增 5 個純邏輯測試（`tests/test_search.py`）覆蓋兩層修正與邊界情況。

**已知限制**：`_SHORT_TERM_MAX_MATCH_RATIO = 0.2` 沒有嚴謹校準過，只用同一支 `app.db` 的幾個詞驗證過方向正確：「汽車」11.6%／「工廠」14.4%（有鑑別力，該保留）vs「畫面」77.4%（沒有鑑別力，該跳過）；門檻用比例（不是絕對筆數）判斷，全域搜尋跟限定單一影片搜尋的候選池大小不同時都適用，但小候選池（例如單一影片內搜尋，片段數可能只有幾十個）下，這個比例門檻有沒有可能對真正有意義的短詞誤判為過度常見，還沒有實際案例驗證過。驗證過程中額外發現 `segments_fts` 有孤兒資料（例如 `全壘打` 的 bm25 命中結果裡有 6 筆 segment id 不在目前的 `segments` 表裡，可能是刪影片時索引沒同步清乾淨），跟這次修正無關，先記錄、沒有處理。

### 否定句查詢的疊加案例：「要真人的畫面，不要出現機器人的畫面」

**背景**：上方「無答案信心判斷」段落已經記錄過「無法處理否定句」是已知限制（BM25 照樣命中被否定的字面關鍵字）。這是對話搜尋實測時額外發現的一個更完整的疊加案例，同時暴露了 `_extract_terms()` 拆詞規則的一個個案缺口。

**現象**：查詢「要真人的畫面 不要出現機器人的畫面」，`_extract_terms()` 拆成 `['要真人', '畫面', '不要', '機器人']`。實測命中數：`要真人` 0 個（`app.db` 沒有任何片段描述會出現「要真人」這種字面組合）、`機器人` 53 個（乾淨命中）。原因是 `_STOPWORDS` 虛詞表（`search.py:65`）沒有把「要」列進去，「要」跟後面的「真人」中間沒有虛詞可以切開，被黏成一個查不到任何東西的複合詞——使用者真正想強調的關鍵字「真人」等於完全沒有被搜尋到，而「機器人」（使用者明確說不要）卻乾淨拿到 53 個片段的真實 bm25 加分。疊加 dense embedding 同樣無法理解「不要」的否定語意（查詢向量仍帶有強烈的「機器人」語意），兩個 channel 一起把機器人片段大幅推到搜尋結果前面，完全違背使用者意圖。

**合理推論（未實測）**：影片庫裡 `video_id=4`《Inside BMW's Super Advanced US Factory Where Robots Build Cars》摘要明確提到「機器人運用於生產線」，其他純真人影片（`video_id=1/5/6` 百大美女、`video_id=3` NBA）摘要完全沒有「機器人」字眼；全域搜尋的影片層級篩選很可能因為查詢字面帶「機器人」而把 BMW 工廠影片判定為最相關，這一段沒有實際呼叫 embedding API 驗證（會有小額真實費用），只是合理推論。

**目前狀態**：小範圍拆詞問題與根本否定語意問題**都已修正**，見下方「否定句偵測與排除」。

### 否定句偵測與排除

**背景**：上方兩段記錄的否定語意限制的根本解法——`_STOPWORDS` 補「要」只解決拆詞黏字問題，BM25／`is_confident` 本身仍然完全看不懂「不要」這種否定詞。

**設計決策**：偵測到否定詞（`_NEGATION_MARKERS = ("不要", "沒有", "不是", "並非")`，只用 golden set／待辦清單裡已經列出的四個，不預先擴充）後面到下一個標點符號之前的內容，**完全排除**含有該內容關鍵字的片段（不進 RRF 融合），不採用扣分方式——直接對應使用者意圖「不要出現」，且 `is_confident` 既有邏輯（top1 是否被 sparse channel 印證）不需要額外改動，排除掉的片段永遠不會變成 top1，是排除的自然副作用。

**實作**（`search.py`）：
- `_split_negated_query(query) -> (positive_text, negative_text)`：用標點符號（不是虛詞表）當否定範圍邊界，避免像「要真人」案例一樣把範圍切太短。
- `_negated_segment_ids(query, valid_ids) -> set[int]`：直接重用 `_sparse_scores()` 對 `negative_text` 取詞比對，連帶重用它既有的 `_SHORT_TERM_MAX_MATCH_RATIO` 比例門檻防呆——避免否定詞剛好是「畫面」這種泛用詞時，誤刪掉大部分候選片段。
- `search()` 在組 `scored` 之前用 `_negated_segment_ids()` 算出要排除的片段，直接從 `segments` 拿掉，不進後續評分與 RRF 融合。
- 刻意不修改 dense embedding 的相似度計算：排除發生在建 `scored` 之前，不管 dense 分數多高，被排除的片段都不會進最終結果，不需要另外處理 dense 端的否定語意。

**驗證結果**：`docs/golden-set.csv` 的 `gs-018`（「工廠裡沒有機器人、全部由人工操作的畫面」，`is_answerable=FALSE`）修正前 `predicted_answerable=True`（誤判為有答案），修正後變成 `False`（正確判斷無答案）；No-answer F1 從 0.545 提升到 **0.667**（No-answer Recall 從 0.75 提升到 1.000）。逐題比對修正前後的完整 17 題結果，**只有 `gs-018` 改變，其餘 16 題完全沒有變動**，確認沒有意外影響其他查詢。

**已知限制**：只用 golden set 這一題驗證過；`_NEGATION_MARKERS` 只有四個詞，沒有涵蓋所有否定表達方式（例如「別」「無」）；否定範圍偵測是規則式（標點符號當邊界），複雜句型（例如否定詞跨越多個子句、雙重否定）沒有測試過。**排除只作用在 sparse／BM25 層級，dense 相似度與影片層級篩選都還是看不懂否定語意，實測發現這個缺口的實際影響比預期大，見下方。**

### 否定句排除後，dense／影片層級篩選仍會讓否定內容大量出現（後續實測發現）

**現象**：對話搜尋實測「要真人的畫面 不要出現機器人的畫面」，排除邏輯本身正確運作（真的排除了 25 個字面包含「機器人」的片段），但最終結果前 10 名有 9 個還是來自 BMW 工廠影片，描述用「機械手臂」「機械人」「機器的工作台」「機器部件」等字——這些字面上都不等於「機器人」，排除邏輯（純字面比對）完全抓不到。

**根因（已確認，直接用 `search.py` 內部函式驗證）**：
1. `_relevant_video_ids()`（影片層級篩選）判定 `video_id=4`（BMW 工廠）跟這句查詢相關，納入候選——因為整句查詢（含「機器人」）embed 出來的向量跟 BMW 摘要（「機器人運用於生產線」）語意接近，這個篩選完全沒有否定感知，是拿完整原始查詢字串去 embed。
2. 結果的 `fusion_score` 都偏低（0.07～0.17，代表 BM25 貢獻很小），`similarity`（dense）0.5～0.57 才是主要排序依據——dense 相似度計算同樣是拿完整原始查詢去 embed，語意上仍然貼近機器人內容，不管句子裡有沒有「不要」。

**目前狀態**：只記錄現象與根因，還沒有修正。可能的修法是讓影片層級篩選與 dense 相似度計算都改用 `_split_negated_query()` 已經算出來的 `positive_text`（去掉否定範圍後的查詢文字）去 embed，而不是完整原始查詢——這是對「否定句偵測」範圍的擴大，之前設計時明確決定「不修改 dense embedding」，這次證實這個範圍對這類案例不夠用；另一個方向是直接做 Reranker（見 [`05-known-limitations-and-open-items.md`](05-known-limitations-and-open-items.md) 待辦事項），用 LLM 對完整查詢語意重新判斷相關性，同時解決否定句、多條件查詢、hard negative 精準率這幾類「需要真正理解語意」的問題，不用為每種語言現象各寫規則。兩個方向都還沒決定要不要做、先做哪個。

## 分析流程平行化

**前提（使用者要求）**：不能改變任何片段會不會被處理、預算會不會截斷、截斷在哪個片段的判斷結果。

**依賴關係分析**：Phase A（場景切分）跟音訊轉錄互不依賴（一個看畫面、一個聽聲音）；Phase E（本地 OCR）跟 Phase F（產生摘要）互不依賴（F 只讀 Phase D 寫入的 `segments`，不碰 Phase E 寫的 `ocr_events`）；Phase B、C 內部「處理完一個片段才檢查一次預算」的順序性是刻意設計，不能打亂。

### Tier 1（零風險，已採用）

三處改成同時起跑，但不改變任何判斷邏輯：

1. Phase A（場景切分）＋ 音訊轉錄同時起跑（`_run_scene_detection_and_transcription()`）。
2. Phase C 片段內字幕／畫面描述／OCR 文字三個 embedding 呼叫改用 thread pool 同時送出（`_embed_segment_texts()`），budget 檢查時機（一個片段三個都做完才檢查一次）不變。
3. Phase E（本地 OCR）＋ Phase F（產生摘要）同時起跑（`_run_local_ocr_and_summary()`）。

**唯一的小副作用（已跟使用者說明並確認接受）**：F 原本用「E 跑完後」的金額判斷要不要花錢做摘要，改成用「E 開始前」的金額判斷，極端情況下兩者合計可能讓總花費比 US$0.20 多出一點點。**UI 小副作用**：狀態列只顯示最新收到的進度訊息，兩個平行 phase 的訊息交錯進佇列，文字可能在階段名稱之間跳動幾次，純顯示層抖動，跟分析結果正確性無關。

### Tier 2（Phase B 批次平行，已採用）

**理由**：Phase B（VLM 逐場景分析）場景數量多（實測 69～160 個），每個都是網路往返，且每次呼叫獨立、無共用模型單例，是純 I/O bound 工作，理論上可以拿到接近線性加速——跟本地 OCR 那種「CPU-bound 共用模型互搶資源」的失敗原因完全不同。

**用真實 rate limit 錯誤訊息回推批次大小**：使用者提供帳號實際撞到的 429 錯誤訊息，確認帳號 `gpt-4o-mini` 的 TPM 上限是 200,000/分鐘且已經實測撞過。用 `tiktoken`（`o200k_base`）精確算出 `vlm.py` 的 `_PROMPT` 是 125 tokens，加上「low」解析度圖片固定 85 tokens，單次呼叫最差情況約 550 tokens。保守起見只讓 Phase B 用量控制在上限一半以內（~100,000 tokens/分鐘），回推批次大小落在 4～6，取中間值 **`VLM_BATCH_SIZE=5`**。

**設計**：`_run_vlm_phase()` 從逐場景改成逐批次，批次內 thread pool 平行送出；用「送出順序」（不是完成順序）收集結果，確保五個平行陣列的索引仍精確對應同一個場景；budget 檢查從「每個場景後」放寬成「每個批次後」（最差多算 `VLM_BATCH_SIZE-1` 個場景的花費，查現有影片花費落在 $0.0965～$0.1885，這個精度差異不會有可觀察的差別）。

**必要配套：429 重試機制**：`_describe_segment_with_retry()` 包住 `vlm.describe_segment()`，收到 `RateLimitError` 等待 `VLM_RATE_LIMIT_RETRY_WAIT_SEC=8.0` 秒後重試，最多 `VLM_RATE_LIMIT_MAX_RETRIES=2` 次。這是序列版本也沒有的保護，因為批次平行後同一批內同時打多個請求會提高撞 429 的機率，不補上會讓平行化反而讓分析更容易失敗。

**真實效能驗證（08-20）**：用 video_id=3（NBA 賽事）真實 20 個場景邊界直接呼叫 `_run_vlm_phase()`：花費 $0.0099，實際 wall-clock 13.2 秒 vs 個別呼叫耗時加總（循序估算）57.3 秒，**加速 4.35 倍**（理論上限是批次大小 5 倍），0 次觸發 rate limit。

**已知限制**：這次測試只涵蓋 20 個場景（3～4 個批次），沒有真的跑滿 69～160 個場景的完整批次數量；`VLM_BATCH_SIZE`／重試參數是用確定的 TPM 數字算出的保守值，不是實測校準值。

### Tier 3（評估後不建議動）

Phase A 本身（有序演算法，切區塊平行掃描會漏掉交界處轉場）、音訊轉錄本身（單一次 API 呼叫，硬切分段會動到 timestamp 銜接邏輯）、Phase D 寫入索引（SQLite 本地寫入本來就快，不是瓶頸）、多支影片之間平行分析（跟既有「序列處理避免同時打多個 API」的設計決策衝突）。

## 重構

兩輪重構的完整過程與每步驟驗證見 [`01-development-timeline.md`](01-development-timeline.md#重構第一輪第二輪)。核心原則：**不改變外部可觀察行為**，只精簡結構、消除重複、補測試。兩輪下來確認的架構事實：`db/`（拆套件後）不 import 任何 `pipeline/`／`ui/`；`pipeline/*` 不 import `ui/*`；依賴方向單向、無循環依賴。`analyzer.py` 刻意維持單一檔案（用具名 phase 函式拆分內部邏輯，不拆成多檔案）——因為它本質是「單一 orchestrator」，拆檔案反而會讓「跑一次分析的完整流程」要跳好幾個檔案才看得懂。
