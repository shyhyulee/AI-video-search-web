# 已知限制、待辦事項與待確認事項

> **類型**：現況參考｜**狀態**：維護中，跟著程式碼更新
> 分類說明與完整索引見 [`README.md`](README.md)。

## 1. 已知限制與風險

### 分析流程

- 場景切分、音訊轉錄的進度百分比都是**預估值**，不是伺服器端真實進度（Whisper API、PySceneDetect 都不提供）。
- 多選批次分析是**序列執行**，不會平行加速——刻意設計，避免同時打多個 API 造成 rate limit 或預算追蹤複雜化。
- AV1 編碼影片的場景切分明顯較慢（實測 602 秒影片約需 79～85 秒，`opencv` backend 只要約 19 秒）。
- `scene_detect._is_av1()` 對 `subprocess.SubprocessError`／`OSError` 靜默吞掉、連 log 都沒有，偵測失敗時悄悄退回 `opencv` backend，除錯時不容易發現。
- 場景長度「死區」（`SPLIT_ABOVE_SEC` ~ `2×MERGE_BELOW_SEC` 之間，目前是 12～16 秒）造成的超長片段沒有絕對上限保證，只在 2 支影片上驗證過。
- 本地 OCR（EasyOCR）時間上限（60 秒）與抽幀密度（每 2 秒、每場景上限 5 張）都是初始猜測值，只用少數已知案例校準過；VLM 覆蓋率低的內容（例如體育賽事）在回合制取樣修正後仍可能無法在時間預算內掃完全部缺口場景。
- 本地 OCR 只做 EasyOCR，Tesseract 條件式複核（Phase 2）尚未實作，也沒有獨立的 exact/BM25 文字檢索通道（Phase 3）——精確代碼查詢（例如型號 `ABC-1234`）目前一律靠 embedding 語意相似度，不保證能穩定命中。
- Phase B 單一場景 VLM 失敗（例如內容審查拒絕）只跳過該場景，不會拖垮整支分析，但沒有「失敗比例過高就整支判定失敗」的斷路器——如果帳號被封、API key 失效這類系統性問題發生，會安靜地生出一支幾乎沒有畫面描述、只有字幕的分析結果（UI 會顯示失敗場景數，但不會主動擋下來）。這是刻意先不做的取捨。
- ~~`BUDGET_USD`（US$0.20）是否要因應場景數變多重新校準還沒正式實測確認~~ **已決策，目前是 US$0.80**：第一次調整起因是 VLM 條件式多幀取樣規劃（見下方「功能延伸」與 [`02-technical-decisions.md`](02-technical-decisions.md#vlm-條件式多幀取樣)）——用真實 7 支影片費用反推，Most Beautiful Faces 系列（觸發率 88～98%）換算後單支費用最高約 US$0.2015，超過原本上限，因此調到 US$0.30。之後長度上限放寬到 1 小時，再補調到 **US$0.80**（見 [`11-web-ui-warm-redesign-plan.md`](11-web-ui-warm-redesign-plan.md) §8.12）。兩次調整都沒有在實際跑滿的真實分析流程裡驗證過餘裕是否足夠。

- **批次分析的總量上限只擋在 UI，後端仍然無限制**：`BUDGET_USD`（目前 US$0.80）是**每支影片**各自計算的，沒有批次層級的預算。前端已於 §8.14 把一次可勾選數限制成 5 支（單批天花板 5×$0.80 = $4.00），但 `POST /api/v1/videos/{id}/analyze` 一次只收一支、本身沒有批次概念，`job_manager` 也只保證「同時只跑一支」、不限制 `queued` 數量——直接打 API 仍然可以無限送。完整的上限對照表見 [`11-web-ui-warm-redesign-plan.md`](11-web-ui-warm-redesign-plan.md) §8.12、§8.14。
- **`MAX_DURATION_SEC` 的 60 分鐘上限實際上碰不到，ASR 會先失敗**：`asr._extract_audio()` 固定輸出 64kbps 單聲道 mp3（實測 7,998 bytes/s），Whisper 的 25MB 上傳上限換算後約 52～55 分鐘，且 ASR 例外會讓整支分析失敗（不是略過字幕繼續跑）。這是從位元率反推的，**沒有用真實長影片實測驗證過**；`BUDGET_USD=0.80` 對 60 分鐘影片的餘裕只有 4.6%（最壞情況外推 $0.765），同樣沒有實測。見 §8.12。

### 搜尋

- ~~無答案信心判斷（`is_confident`）無法處理否定句~~ **已修正（sparse 層級）**：`search.py` 新增 `split_negated_query()`／`negated_segment_ids()`，偵測到「不要／沒有／不是／並非」後面的關鍵字就把字面命中的片段整個排除，不進 RRF 融合，`is_confident` 判斷因此自然一併修好。詳見 [`02-technical-decisions.md`](02-technical-decisions.md#否定句偵測與排除)。已知限制：`_NEGATION_MARKERS` 只有四個詞；只用 golden set 一題（`gs-018`）驗證過，複雜句型沒測過。
- **否定句排除只有 sparse 層級有效，dense 相似度與影片層級篩選仍然完全看不懂否定語意**：實測「要真人的畫面 不要出現機器人的畫面」，排除邏輯正確排除了字面命中「機器人」的 25 個片段，但結果前 10 名仍有 9 個來自 BMW 工廠影片（用「機械手臂」「機械人」等字面不同但語意相同的詞描述），原因是 `relevant_video_ids()`（影片層級篩選）與逐片段 dense 相似度計算都還是拿完整原始查詢（含否定內容）去 embed。詳見 [`02-technical-decisions.md`](02-technical-decisions.md#否定句排除後dense影片層級篩選仍會讓否定內容大量出現後續實測發現)。
- **對話搜尋的否定句排除依賴否定詞字面存活到 `search()` 收到的查詢字串**：`pipeline/intent.py` 的 LLM 會把使用者原句改寫成 `standalone_query`，如果 LLM 把「不要」換成「避免」「排除」等沒有列在 `_NEGATION_MARKERS` 裡的說法，否定排除會整個失效且不會有任何錯誤或警告——這個風險還沒有實際驗證過會不會發生、多常發生。
- **不支援布林式複合搜尋**：UI 只有「查詢字串」與「搜尋範圍」兩個條件（範圍現在可以是任意一批影片，不再只有「全部／單一」），沒有 `AND`／`OR`／引號片語／欄位限定語法。輸入多個關鍵字時，dense channel 把整句壓成一個語意向量（偏 AND 的傾向但不強制），sparse channel 則是明確的 `OR`（`db/segments.py` 的 `fts_bm25_search()` 用 `" OR ".join`），唯一真正的複合條件是否定範圍排除（`AND NOT`）。另一個容易踩到的點是關鍵字之間沒有空白或虛詞時會被 `extract_terms()` 黏成單一複合詞，trigram 片語查詢等同子字串比對而通常一無所獲。完整說明見 [`12-search-query-logic.md`](12-search-query-logic.md#4-複合搜尋輸入多個關鍵字會發生什麼)。golden set 目前沒有多關鍵字複合查詢的題目，現況準確率未知。
- ~~sparse channel 的範圍過濾在 Python 端做，`LIMIT 200` 名額會被範圍外的片段佔走~~ **已修**：`fts_bm25_search()`／`fts_like_search()` 新增 `video_ids` 參數，`_BM25_SQL` 最前面加一個 `scope` CTE（`NOT MATERIALIZED`，否則 pg_trgm GIN 索引吃不到），`stats`／`df`／`hits` 三個 CTE 一律只看範圍內的片段。修之前限定範圍搜尋時 sparse channel 常常整個落空（RRF 只剩 dense、`is_confident` 恆為 false），而且**單支影片的舊行為就已經有這個缺陷**，不是多選才引入的。`video_ids` 為 `NULL` 時語意與修改前逐字相同，全域搜尋（含 golden set 評測走的路徑）行為不變。已知限制：這只解決「限定範圍」的情形，全域搜尋的 200 名額截斷仍在。
- 影片層級篩選（`MIN_RELEVANCE`／`RELEVANCE_MARGIN`）只用兩支真實影片、幾組查詢實測驗證過，不是嚴謹調校的結果。**限定搜尋範圍時完全不套用**（不論選一支或多支），這是刻意的：使用者已經明確指定範圍，系統不該再用摘要相似度二次猜測。
- **限定範圍搜尋這條路徑沒有進過 golden set 評測**：`pipeline/evaluation.py` 呼叫 `search()` 時不傳範圍參數，17 題全部是全域搜尋。所以「選了 N 支影片之後的準確率」是未知數，多選範圍上線後也還是未知數。
- 搜尋成本已寫進 `search_log` 表、單次花費會顯示在搜尋結果頁籤，但**沒有上限或警示機制**，使用者可以無限次搜尋；Header 也沒有搜尋累計成本的統計卡，只能查資料庫。
- Hybrid BM25 的虛詞表是針對目前這批 17 題 golden set 手動調的，沒驗證過更多樣查詢下的失敗率；`RRF_K=5` 只掃過 60/20/10/5 四個點就定案，沒有測過更小的 k（1、2）會不會出現反轉或不穩定。`RRF_K` 與 `MIN_FUSION_SCORE=0.1` 這兩個常數**沒有一起校準過**：兩者相乘隱含「只靠 dense 命中的片段必須排進 dense 前 5 名才會出現在結果裡」這條規則（`1/(5+5)=0.1` 剛好達標），調整 `RRF_K` 會連帶改變這條規則的鬆緊，見 [`12-search-query-logic.md`](12-search-query-logic.md#min_fusion_score-與-rrf_k-的隱含規則推論未實測)。
- 現有 golden set 評測 baseline（見 [`04-testing-and-evaluation.md`](04-testing-and-evaluation.md#5-評測-baseline-的時效性警示)）在場景長度改成 8～12 秒後，一旦重新分析影片或重建 golden set 就會失去比較基準。

### 影片內容整理成文件

- **文件品質沒有任何量化方式**。搜尋有 golden set 可以算 Recall@K／MRR，文件整理沒有——只能人工看。目前的驗收就是實跑 4 支影片、人眼確認 doc_type 判對、步驟順序合理、時間戳對得上。這代表**之後改 prompt 沒有回歸測試可擋**，改壞了不會有人發現。
- **幻覺步驟的風險只被緩解、沒有被消除**。緩解手段是「每個步驟必須附時間戳」＋「講不出來的寫進 uncovered」，實測 4 支都沒發現編造的步驟（壽司那支的「保留 3 公分」「靜置 10 分鐘」查過，逐字來自 `ocr_text`），但這是 4 支的樣本，不是保證。SOP 類文件尤其要注意——一份看起來很專業但編造的製程文件比沒有更糟。
- **步驟的時間順序沒有被強制**。實測 video 29（線性代數）出現過 `[00:48]` 排在 `[00:38]` 前面。程式沒有依 `timestamp_sec` 排序，完全靠模型自己排。
- **`segments.ocr_text` 有 21/1,156 個片段是字面字串 `"null"`**（VLM 回傳的字串沒被正規化成 NULL）。`document.py` 的 `_clean()` 在組 prompt 時濾掉了，但**資料庫裡的髒資料沒有回填修正**，其他讀 `ocr_text` 的地方（搜尋的 `content` generated column）還是會吃到。
- **Whisper 的幻覺字幕過濾沒攔到外語幻覺**。video 13（壽司，純音樂無人聲）的字幕是 `Девочка-пай`、`Редактор субтитров А.Семкин`（俄文字幕製作人員名單，典型的 Whisper 幻覺），`asr.py` 現有的兩種過濾模式（`no_speech_prob` 偏高、單字重複）都沒抓到。文件產生器靠 prompt 規則繞過去了，但**這些幻覺文字仍然進了 embedding 與 BM25 索引**，是搜尋端的既有問題。
- **文件重新整理直接覆蓋，沒有版本歷史**。想比較兩次結果只能自己先複製走。
- 文件成本累加進 `videos.cost_usd`，跟摘要一樣沒有獨立欄位，所以**看不出一支影片的成本裡有多少是文件整理**。

### 文件與程式碼一致性

- `scripts/run_golden_set_eval.py` 的檔案開頭註解仍寫「對 18 題全部跑一輪」，但 golden set 定案後實際是 17 題（`gs-009` 已刪除）——這是程式碼註解沒有跟著資料異動更新的殘留文字。

## 2. 待辦事項

### 場景長度變更的後續

- [ ] 重新產生 `golden-set.csv` 的 `expected_start`／`expected_end`（配合場景長度已改 8～12 秒）
- [ ] `app.db` 既有已分析影片重新分析以套用新場景長度（會產生 API 費用，待決定要不要做）
- [ ] 重新產生 golden set 後，用新 baseline 重跑一次 Hybrid+RRF／無答案判斷的評測，確認結論是否仍然成立

### 功能延伸

- [ ] 整理成文件：下載成 Markdown／txt 檔（`CLAUDE.md` 已有檔名慣例但沒有任何程式碼實作，全站也還沒有「產生檔案給使用者下載」的機制）
- [x] ~~整理成文件：點時間戳跳到影片對應位置~~ **已完成（2026-08-30）**：點了才出現播放器（刻意不常駐，理由見 `VideoDetailPanel`），同一支影片內換步驟直接 seek
- [ ] 整理成文件：依 `timestamp_sec` 排序步驟，不要完全信任模型自己排的順序
- [ ] 本地 OCR：校準時間上限／取樣密度，特別是針對 VLM 覆蓋率低的內容（例如體育賽事）
- [ ] 本地 OCR Phase 2：Tesseract 條件式複核（需要系統安裝 `tesseract-ocr`，屆時另行確認）
- [ ] 獨立 OCR exact/BM25 檢索通道（Phase 3，需要跟搜尋現有的 Hybrid BM25 協調，不要重複做一套）
- [ ] 搜尋累計成本的 Header 統計卡，以及搜尋花費上限／警示機制
- [x] ~~VLM 條件式多幀取樣~~ **已實作並驗證（只重跑 video 1）**，見 [`02-technical-decisions.md`](02-technical-decisions.md#vlm-條件式多幀取樣)／[`04-testing-and-evaluation.md`](04-testing-and-evaluation.md#6-vlm-條件式多幀取樣上線後的驗證只重跑-video-1)。**後續待辦**：其餘 6 支影片還沒用新邏輯重新分析（會花錢、也會讓現有 golden set baseline 失去比較基準）；`VLM_BATCH_SIZE=3` 只驗證過 video 1（觸發率 85%）這一種分布，沒驗證過觸發率低很多的影片；驗證發現多幀取樣會「轉移」而非單純疊加涵蓋範圍（gs-001 從穩定命中退步成排名第 2），固定 2 幀 30%/70% 的取樣密度對轉場密集的內容仍然不夠，要不要加大幀數或改用不等比例取樣還沒決定。
- [ ] 搜尋準確率提升需求（見 [`00-overview.md`](00-overview.md#23-搜尋準確率提升需求)）Phase 1 尚未做完的部分：相鄰片段合併／Temporal NMS；Phase 2：**Top 20-50 Reranker**（用 LLM 對完整查詢語意重新判斷相關性，能同時解決否定句、多條件查詢、hard negative 精準率這幾類「需要真正理解語意」的問題，見上方否定句排除的已知限制——這是目前判斷投報率最高的下一步，但還沒設計）、依查詢類型動態調整模態權重

### 文件維護

- [ ] 修正 `scripts/run_golden_set_eval.py` 開頭註解的「18 題」為「17 題」
- [x] ~~補齊 `development-log.md` 的 08-20 條目~~ **不再適用**：`development-log.md` 與 `changelog/` 都已不存在（從未進過版控），[`01-development-timeline.md`](01-development-timeline.md) 就是目前唯一且完整的開發歷程記錄。

## 3. 待確認事項

- **場景長度重新校準的優先順序**：`app.db` 重新分析／golden set 重建要不要做、什麼時候做，會影響能不能信任之後任何搜尋實驗的評測結果。
- **本地 OCR 抓到的文字要不要在 UI 上標示來源引擎**（VLM-OCR vs 本地 OCR），或維持現狀自然併入 `ocr_text` 顯示、不特別區分。
- **Whisper 幻覈過濾的已知取捨**：如果未來真的出現「連續 3 次以上喊同一句口號／副歌」的真實內容被模式 B 誤過濾，要不要放寬門檻——目前判斷是刻意接受的取捨，不是要修的 bug，但需要真實案例出現才能重新評估。
- **重構第二輪標記為 Low 但沒有處理的 2 個觀察項目**：`scene_detect._is_av1()` 補 log（見上方已知限制）、`library_tab._set_thumbnail()` 跟 `pipeline/frames.py` 的縮圖抽幀邏輯概念重疊——兩者都判斷過「先觀察不建議動」，如果之後有新證據顯示值得處理，可以重新評估。
- **否定句排除擴大到 dense／影片層級篩選，還是直接做 Reranker，還是兩個都做**：兩個方向都能解決「否定句排除只有 sparse 層級有效」的問題，前者範圍小（重用 `split_negated_query()` 的 `positive_text` 去 embed）、只解決否定句這一類；後者範圍大（Top 20-50 LLM 重排），但能同時解決否定句、多條件查詢、hard negative 精準率好幾類問題。還沒決定要不要做、先做哪個。
