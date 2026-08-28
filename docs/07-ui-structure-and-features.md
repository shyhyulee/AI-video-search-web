# Tkinter UI — 功能與結構設計

> **類型**：歷史存檔｜**狀態**：所描述的 Tkinter 程式碼已移除，唯讀
> 分類說明與完整索引見 [`README.md`](README.md)。

## 1. 文件目的

整理 `src/ai_video_search_web/app.py`、`src/ai_video_search_web/theme.py` 與 `src/ai_video_search_web/ui/` 底下目前實作的 Tkinter UI，記錄各頁籤的功能、版面結構、共用元件與跨頁籤互動方式，供之後維護或擴充 UI 時查閱。內容依實際程式碼整理，不包含尚未實作的規劃項目（規劃項目見 [`00-overview.md`](00-overview.md) 與 [`05-known-limitations-and-open-items.md`](05-known-limitations-and-open-items.md)）。

## 2. 整體架構

### 2.1 進入點與視窗組裝（`app.py`）

`App(tk.Tk)` 是唯一的頂層視窗：

- 標題「AI 影片搜尋」，初始尺寸 `1366x768`，最小尺寸 `1024x640`。
- 啟動時呼叫 `db.init_db()`，並用 `theme.configure_style()` 統一設定 `ttk.Style`（`theme_use("clam")`）。
- 版面由上而下兩塊：`HeaderFrame`（row 0）＋ `ttk.Notebook`（row 1，五個頁籤）。

**頁籤建構順序有相依性**（程式碼內有明確註解）：

```text
search_tab → library_tab → video_tab → conversation_tab → logs_tab
```

原因：`video_tab` 建構時會立刻觸發 `on_stats_changed`（載入待分析清單那一刻），而 `on_stats_changed` 也會刷新 `library_tab`；`library_tab` 又依賴 `search_tab.get_recent_queries`。所以 `search_tab` 必須最先建好，`library_tab` 其次，`video_tab` 最後。

五個頁籤依 Notebook 加入順序顯示：

| 順序 | 頁籤文字 | 類別 | 檔案 |
|---|---|---|---|
| 1 | 影片與分析 | `VideoAnalysisTab` | `ui/video_tab.py` |
| 2 | 影片庫 | `LibraryTab` | `ui/library_tab.py` |
| 3 | 搜尋結果 | `SearchResultsTab` | `ui/search_tab.py` |
| 4 | 對話搜尋 | `ConversationTab` | `ui/conversation_tab.py` |
| 5 | 處理紀錄 | `ProcessingLogTab` | `ui/logs_tab.py` |

> 待確認：`00-overview.md` 描述產品需求時只列出四個頁籤（無「對話搜尋」），實際程式碼已有五個頁籤，「對話搜尋」為之後新增的獨立入口（見 `conversation_tab.py` 模組註解），`00-overview.md` 尚未同步更新。

### 2.2 共用基礎設施

| 檔案 | 行數 | 用途 |
|---|---:|---|
| `theme.py` | 251 | 顏色、間距、字型、`ttk.Style` 統一設定 |
| `ui/widgets.py` | 207 | 格式化函式與跨頁籤共用小元件 |
| `ui/playback.py` | 40 | 共用的「用 ffplay 播放片段」邏輯 |
| `ui/header.py` | 43 | 全域 Header |

所有 Widget 只引用 `theme.py` 定義的 style name／常數，不在個別檔案分散設定顏色。

## 3. 全域 Header（`ui/header.py`）

`HeaderFrame` 左右兩欄：

- 左側：標題「AI 影片搜尋」＋副標「快速找到影片中的關鍵時刻」。
- 右側：四張 `StatCard`（標籤字小、數值字大）：

| 卡片 | 資料來源 |
|---|---|
| 待分析 | `stats.pending_count` |
| 已分析 | `stats.analyzed_count` |
| 影片片段 | `stats.segment_count` |
| 累計成本 | `stats.total_cost_usd`（`format_cost` 格式化為 `US$x.xx`） |

`update_stats(stats)` 供 `App._on_stats_changed()` 即時更新四張卡片，不需重建元件。

## 4. 共用元件與格式化函式（`ui/widgets.py`）

### 4.1 格式化函式

| 函式 | 用途 |
|---|---|
| `format_analysis_result_note(item)` | 組合「預算截斷」與「場景畫面分析失敗」附註（兩者可能同時發生，不可共用同一句文字，避免誤導原因） |
| `format_duration(seconds)` | 秒數轉 `mm:ss` 或 `h:mm:ss` |
| `format_datetime_display(iso_str)` | ISO 字串轉 `YYYY/MM/DD HH:MM` |
| `format_time_range(start_sec, end_sec)` | 轉 `mm:ss–mm:ss` |
| `format_cost(usd)` | 轉 `US$x,xxx.xx` |
| `format_percent(ratio)` | 轉整數百分比 |
| `truncate(text, limit)` | 單行截斷＋省略號，換行先轉空白 |

### 4.2 共用元件

| 元件 | 用途 |
|---|---|
| `StatCard` | Header 右側指標卡（標籤＋數值，可 `set_value()` 更新） |
| `EmptyState` | 取代空表格的置中提示區塊（標題＋多行提示） |
| `Badge` | 小型狀態標籤，底色＋文字辨識（不只靠色相），色系見 `theme.BADGE_BG`／`BADGE_FG` |
| `SimilarityBar` | 相似度色條＋百分比文字，同樣不只靠顏色傳達分數 |
| `make_scrollable_treeview(...)` | 建立帶垂直捲軸的 `ttk.Treeview`，回傳 `(容器, tree)` |
| `make_scrollable_frame(parent)` | 建立可垂直捲動容器（`tk.Canvas` + 內層 Frame），滑鼠移入才綁定滾輪事件，移出即解除，避免多個可捲動區域互相搶滾輪 |

## 5. 共用播放邏輯（`ui/playback.py`）

`play_segment(video_id, video_title, start_sec, end_sec)`：查出影片檔案路徑，用 `ffplay -autoexit -ss <start> -t <duration>` 播放指定片段。找不到影片紀錄或啟動播放器失敗（`OSError`）都用 `messagebox.showwarning` 提示，不讓例外往外拋出干擾事件迴圈。`search_tab.py`／`conversation_tab.py` 共用此函式。

## 6. 各頁籤功能與結構

### 6.1 影片與分析（`VideoAnalysisTab`，`ui/video_tab.py`，445 行）

**功能**：新增影片（YouTube 下載／選擇本機影片）、管理待分析清單、觸發分析。

**版面**：上下兩張卡片。

1. **新增影片卡片**
   - YouTube 網址輸入框＋「下載影片」按鈕：檢查網址格式（`downloader.is_youtube_url`）與是否已存在（`db.find_by_source_url`），呼叫 `downloader.start_download()`，用 `queue.Queue` + `self.after(150, ...)` 輪詢下載進度（百分比／速度／剩餘時間），完成後寫入 DB（`db.insert_video`，`source=SOURCE_YOUTUBE`）。
   - 「選擇本機影片」按鈕：`filedialog.askopenfilename`（支援 MP4/MOV/MKV/WebM），用 `ffprobe` 讀取長度（讀不到不擋流程），寫入 DB（`source=SOURCE_LOCAL`）。
   - 進度條（`Primary.Horizontal.TProgressbar`）＋狀態文字（secondary／error／success 三種樣式）。

2. **待分析影片列表卡片**
   - 可複選（`selectmode="extended"`）`Treeview`：影片名稱／長度／來源／加入時間／狀態，無資料時顯示 `EmptyState`。
   - 工具列：
     - 「開始分析」：檢查選取影片是否超過長度上限（`analyzer.is_within_duration_limit`／`MAX_DURATION_SEC`），超過的用 `messagebox` 列出並跳過；其餘依序逐一呼叫 `analyzer.start_analysis()`，用 queue 輪詢進度（`AnalysisProgress`／`AnalysisResult`／`AnalysisError`），完成一支才開始下一支，全部完成後刷新清單並觸發 `on_stats_changed`。
     - 「移除」：`messagebox.askyesno` 確認後，刪除 DB 紀錄（`db.delete_video`）與磁碟檔案（刪檔失敗會另外跳警告，不中斷其餘刪除）。

### 6.2 影片庫（`LibraryTab`，`ui/library_tab.py`，625 行）

**功能**：搜尋入口、已分析影片列表（可排序／篩選）、詳細資訊與摘要、重新分析。

**版面**：上方搜尋列卡片＋下方 `PanedWindow`（水平分割，左 weight=3／右 weight=2）。

1. **搜尋列卡片**：查詢輸入框＋「搜尋」按鈕（呼叫外部傳入的 `on_search` callback，由 `App` 導向切換到「搜尋結果」頁籤）；「最近搜尋」用 `Link.TButton` 列出（資料來自 `search_tab.get_recent_queries`，最多 5 筆）。

2. **左側：影片列表**
   - 篩選按鈕列（單選，選中樣式切換為 `Primary.TButton`）：全部／分析完成／分析失敗／無字幕／純畫面。
   - 可排序 `Treeview`：影片名稱／長度／片段數／分析狀態／成本／分析日期，點擊可排序欄位標題切換排序方向（`title`／`segment_count`／`cost`／`analyzed_at`）。
   - 無資料或篩選後無結果時顯示對應的 `EmptyState`。

3. **右側：詳細資訊面板**（外層用 `make_scrollable_frame` 包住，確保底部按鈕不被內容擠出畫面外）
   - 縮圖：用 `ffmpeg` 擷取影片中點畫面產生暫存 PNG 顯示，失敗則顯示「無法產生縮圖」文字。縮圖容器用固定像素尺寸的 `tk.Frame` 包住 `tk.Label`（`grid_propagate(False)`），避免 `tk.Label` 在無圖片時把 `width`/`height` 當成字元數計算，撐爆版面。
   - 標題、meta（長度／片段數／分析時間／成本）、三個 `Badge`（有字幕／有畫面描述／有 OCR）。
   - 摘要文字（`video.summary`；未分析成功或尚無摘要時顯示對應提示文字）。
   - 三個操作按鈕：
     - 「重新產生摘要」：背景 `threading.Thread` 呼叫 `summary_pipeline.generate_summary`，完成後寫回 DB 並 `refresh()`。
     - 「在此影片內搜尋」：呼叫 `on_search_in_video` callback，帶 `video_id`／`video_title` 導向搜尋結果頁籤並設定範圍。
     - 「重新分析」：`messagebox.askyesno` 確認（會清除既有片段／字幕／畫面描述／OCR／摘要），呼叫 `db.reset_to_pending()` 後重跑 `analyzer.start_analysis()`。重新分析期間 `refresh()` 會被忽略（避免該影片狀態暫時變成 pending 而從列表消失、造成畫面閃爍），改由分析結束的 callback 自己呼叫 `refresh()`。

### 6.3 搜尋結果（`SearchResultsTab`，`ui/search_tab.py`，436 行）

**功能**：語意搜尋輸入、結果列表、詳細分數面板、片段播放、CSV 匯出。也是「影片庫」與其他頁籤導向搜尋的共用進入點（對外提供 `run_search()`／`set_scope()` 方法）。

**版面**：上方搜尋列卡片＋下方 `PanedWindow`（左 weight=3／右 weight=2）。

1. **搜尋列卡片**：範圍列（僅在「在此影片內搜尋」時顯示，可按「清除範圍」還原成全部影片）、查詢輸入框、「搜尋」／「匯出 CSV」按鈕、狀態文字（找到筆數／耗時／花費，或錯誤訊息）。

2. **左側：結果列表**
   - `Treeview`：排名／影片名稱／時間範圍／相似度／融合分數／命中來源／片段描述（單擊選取看詳細，雙擊或 Enter 播放片段）。
   - 工具列：「播放片段」／「查看詳細」按鈕＋操作提示文字。
   - 無查詢、搜尋中無結果、搜尋錯誤三種情境各自對應不同的 `EmptyState` 文案。

3. **右側：詳細資訊面板**：`SimilarityBar`（最終相似度）＋各模態分數（字幕／畫面／OCR／融合分數／命中策略，缺值顯示 `N/A`）、片段描述、字幕內容。

4. **背景搜尋**：`threading.Thread` 呼叫 `search_pipeline.search()`，`queue` + `after(150, ...)` 輪詢結果；例外一律攔截後包成物件放進 queue，避免背景執行緒例外直接中止程式。

5. **CSV 匯出**：`filedialog.asksaveasfilename`，`utf-8-sig` 編碼（相容 Excel 開啟中文），欄位為排名／影片名稱／時間範圍／相似度／融合分數／命中來源／片段描述。

### 6.4 對話搜尋（`ConversationTab`，`ui/conversation_tab.py`，274 行）

**功能**：多輪對話式影片搜尋（例如先問「找出有人進入生產線的畫面」，接著追問「只看穿紅色衣服的人」或「播放第二段」）。

模組註解明確說明設計意圖：這是新增的獨立入口，**不改動**既有「搜尋結果」頁籤的單次關鍵字搜尋行為；兩者共用 `pipeline/search.py` 與播放邏輯（`ui/playback.py`），並沿用 `search_tab.py` 既有的「背景執行緒 + queue + `after(150, poll)`」模式，不重複實作。

**版面**：`PanedWindow`（垂直分割，上 weight=3／下 weight=2）。

1. **上方：對話區**：唯讀 `tk.Text` 訊息串（`user`／`assistant` 兩種文字樣式，助理訊息灰階顯示）＋輸入框＋「送出」按鈕；初始顯示固定問候語（`_GREETING`）。

2. **下方：這一輪的相關片段**：`Treeview`（欄位與「搜尋結果」頁籤相同：排名／影片名稱／時間範圍／相似度／融合分數／命中來源／片段描述），雙擊或 Enter 播放。

3. **對話狀態**：`conversation_pipeline.ConversationState` 由 `ConversationTab` 持有並在每輪呼叫 `conversation_pipeline.handle_turn(state, message)` 後更新（`new_state`／`reply_text`／`results`／`cost_usd`）；背景執行緒呼叫、queue 輪詢，例外處理方式與 `search_tab.py` 相同。

### 6.5 處理紀錄（`ProcessingLogTab`，`ui/logs_tab.py`，253 行）

**功能**：把整支程式的 `logging` 輸出即時顯示成可篩選、可匯出的列表，是**整支程式唯一掛 `logging.Handler` 的地方**。

- `_QueueLogHandler`：`emit()` 只把 `LogRecord` 轉換成 `_LogEntry` 塞進 `queue.Queue`，不碰任何 Tk 元件（因為可能從背景執行緒——search/summary worker——被呼叫）。UI 端用 `after(150, ...)` 輪詢 queue 取出後才更新 `Treeview`。
- 記錄用 `deque(maxlen=1000)` 限制記憶體用量；畫面顯示新的在最上面，匯出 CSV 則改回正序（舊→新），符合一般 log 檔閱讀習慣。
- 篩選：全部／INFO／WARNING／ERROR（單選按鈕列，同 `library_tab` 的篩選樣式）。依等級上色：ERROR 紅、WARNING 橙、INFO 灰（`theme.ERROR`／`WARNING`／`TEXT_SECONDARY`）。
- 工具列：「清除畫面」（連記憶體緩衝一起清空，不是只隱藏，避免切換篩選讓舊紀錄「復活」）、「匯出 Log」（CSV，含完整 traceback）、「複製錯誤」（選取列的完整 detail 複製到剪貼簿）。
- 每筆 log 帶 `video_title`／`pipeline_stage` 兩個自訂欄位（透過 `logger.error(..., extra={...})` 傳入），供 Treeview 顯示與篩選脈絡。

## 7. 跨頁籤互動（`app.py` 組裝層）

| Callback | 觸發方 | 行為 |
|---|---|---|
| `_on_stats_changed` | `video_tab`（分析完成）／`library_tab`（摘要更新、重新分析完成） | 重新讀取 `db.get_header_stats()`，更新 Header 四張卡片，並呼叫 `library_tab.refresh()`（讓分析剛完成時即時反映在影片庫列表，不用等使用者手動切換分頁） |
| `_on_search_from_library` | `library_tab` 搜尋列 | 呼叫 `search_tab.run_search(query)`，並 `notebook.select(search_tab)` 切換分頁 |
| `_on_search_in_video` | `library_tab`「在此影片內搜尋」按鈕 | 呼叫 `search_tab.set_scope(video_id, video_title)`，並切換到搜尋結果分頁（不自動搜尋，等使用者輸入查詢） |
| `_on_tab_changed`（綁定 `<<NotebookTabChanged>>`） | Notebook 分頁切換 | 切到「影片庫」分頁時呼叫 `library_tab.refresh()` |

## 8. 非同步處理模式

下載、分析、搜尋、摘要產生、對話回合這幾個耗時操作全部遵循同一套模式，避免卡住 Tkinter 主執行緒（event loop）：

1. 建立一個 `queue.Queue()`。
2. 耗時工作丟給背景 `threading.Thread`（或既有的 `subprocess` 型 downloader／analyzer），執行過程中把進度物件（例如 `AnalysisProgress`）或最終結果（`AnalysisResult`／`AnalysisError`、`SearchResponse`、例外物件）放進 queue。
3. UI 端呼叫 `self.after(150, poll_fn)` 每 150ms 輪詢一次 queue（`queue.Queue.get_nowait()` + `except queue.Empty`），有資料才更新畫面，沒有就排下一次輪詢。
4. 背景執行緒內一律用 `try/except Exception` 攔截 API／網路例外，包成例外物件放進 queue；UI 端統一用 `isinstance(item, Exception)` 判斷並顯示錯誤訊息，不讓背景執行緒的例外直接讓程式崩潰。

## 9. 視覺設計系統（`theme.py`）

### 9.1 顏色

| 用途 | 常數 | 值 |
|---|---|---|
| App 背景 | `BG_APP` | `#F5F7FA` |
| 卡片背景 | `BG_CARD` | `#FFFFFF` |
| 主要文字 | `TEXT_PRIMARY` | `#172033` |
| 次要文字 | `TEXT_SECONDARY` | `#667085` |
| 品牌主色 | `PRIMARY` / `PRIMARY_HOVER` | `#2563EB` / `#1D4ED8` |
| 成功／警告／錯誤 | `SUCCESS` / `WARNING` / `ERROR` | `#16A34A` / `#D97706` / `#DC2626` |
| 邊框 | `BORDER` | `#D0D5DD` |
| 選取列底色 | `ROW_SELECTED` | `#E8F1FF` |

`Badge` 用淺色底＋深色字（`BADGE_BG`／`BADGE_FG`，success/warning/error/neutral/primary 五種），避免只靠色相辨識狀態。

### 9.2 間距（8px 系統）

`SPACE_4`／`SPACE_8`／`SPACE_16`／`SPACE_24`／`SPACE_32`，全 UI 版面留白統一從這五個常數取值。

### 9.3 字型

`_resolve_font_family()` 依作業系統挑選中文字型：Windows 優先 `Microsoft JhengHei UI`，其餘系統優先 `Noto Sans CJK TC`，找不到則依序 fallback（`Noto Sans CJK TC` → `Microsoft JhengHei` → `PingFang TC` → `sans-serif` → `TkDefaultFont`）。`FONT_FAMILY` 在 `configure_style()`（root `Tk` 建立後）才會被填入，四個字級函式：`font_title()`／`font_section()`／`font_body()`／`font_caption()`（對應 20／15／11／10pt，皆可傳 `bold`）。

### 9.4 `ttk.Style` 命名慣例

`configure_style(style)` 在 root 建立後呼叫一次，集中設定所有樣式，個別頁籤只引用 style name：

- 容器／文字：`Card.TFrame`、`TLabel` 與其 `Card`／`Secondary`／`Error`／`Success` 各種組合、`Title.TLabel`、`Section.TLabel`、`StatValue.TLabel`、`StatLabel.TLabel`。
- 按鈕：`Primary.TButton`（全應用程式只用一種主要樣式）、`Secondary.TButton`（次要操作）、`Link.TButton`（文字連結樣式，如「最近搜尋」）。
- 其餘：`TEntry`／`TCombobox`（focus 時邊框變 `PRIMARY`）、`TNotebook.Tab`（選中變卡片背景＋品牌色文字）、`Treeview`／`Treeview.Heading`（選取列 `ROW_SELECTED`）、`Primary.Horizontal.TProgressbar`、`Vertical.TScrollbar`。

## 10. 已知限制與注意事項

- 縮圖產生（`library_tab`）、本機影片長度探測（`video_tab`）、片段播放（`playback.py`）都依賴外部指令 `ffmpeg`／`ffprobe`／`ffplay`，需存在於系統 `PATH`；三處都已用 `try/except` 包住失敗情境，不會讓程式崩潰，但功能會退化（無法產生縮圖／長度顯示 `--:--`／播放失敗跳警告）。
- `App._on_tab_changed` 用字串比較 `self.notebook.select() == str(self.library_tab)` 判斷目前分頁，依賴 Tkinter 內部的 widget path 字串表示法。
- `library_tab` 重新分析期間會忽略外部觸發的 `refresh()`（見 6.2 節「重新分析」），這是刻意設計，避免列表項目在分析中途因狀態變成 pending 而暫時消失。
- 「對話搜尋」頁籤已存在於程式碼但未反映在 `00-overview.md` 的產品需求描述中（待確認：是否需要回頭更新該文件）。
