# 文件索引

這個資料夾的 Markdown **性質不同、維護方式也不同**。進來之前先看這張分類表，
不要把「三個月前的執行計畫」當成「現在的系統長相」來讀。

**分類寫在目錄結構上，不只寫在這份索引裡**（2026-09-02 分層）：

```text
docs/
  *.md          現況參考與開發歷程——描述系統現在的樣子，跟著程式碼更新
  archive/      執行紀錄與歷史存檔——任務已結束，唯讀，不要回頭改寫
  prompts/      原始需求 prompt——使用者當初交付的規格原文，唯讀不改
```

只有**任務已經結束**的執行紀錄才進 `archive/`。仍在追加的（`05 §8`、`09` 的 P5）
留在頂層——`archive/` 的意思是「這件事做完了」，不是「這份比較舊」。

每份文件開頭都有一行 `> **類型**：…｜**狀態**：…` 標頭，跟這裡的分類一致。

## 三種類型

| 類型 | 意思 | 該怎麼讀 |
|---|---|---|
| **現況參考** | 描述系統「現在」是什麼樣子 | 可以直接當事實用；跟程式碼不符就是 bug，請修文件 |
| **執行紀錄** | 某個任務的計畫與過程 | 已結束的收在 `archive/`，**唯讀**；裡面的「目前狀態」是當時的，不是現在的 |
| **原始需求 prompt** | 使用者當初交付給 Claude Code 的規格原文 | 收在 `prompts/`，**唯讀不改**。要看「後來實際怎麼做」請看對應的執行紀錄 |

## 現況參考（會跟著程式碼更新）

| 文件 | 回答什麼問題 |
|---|---|
| [`00-overview.md`](00-overview.md) | 專案全貌：背景需求、技術棧、模組分層、資料流、成本與限制。**不知道從哪開始就看這份** |
| [`02-technical-decisions.md`](02-technical-decisions.md) | 「這個功能為什麼這樣設計」——每個決策的背景、比較過的選項、實測數據；最後一章 [已排除方案](02-technical-decisions.md#已排除方案) 收「已經試過、不要再試一次的做法」 |
| [`03-testing-and-evaluation.md`](03-testing-and-evaluation.md) | 測試怎麼跑、搜尋品質怎麼量、Golden Set baseline 是多少 |
| [`04-known-limitations-and-open-items.md`](04-known-limitations-and-open-items.md) | 「還有什麼沒做完、哪些數字還不能全信」——已知限制、待辦、待確認 |
| [`06-search-query-logic.md`](06-search-query-logic.md) | 一次搜尋的完整處理順序、多關鍵字複合搜尋的真實行為；§7 是「AI對話」頁在同一條檢索之上多做的那一層 |
| [`08-local-startup-guide.md`](08-local-startup-guide.md) | 怎麼把專案跑起來、怎麼驗證、卡住了怎麼查、怎麼用 pgAdmin 看資料 |
| [`10-技術詳解-五個技術層與分析流程.html`](10-技術詳解-五個技術層與分析流程.html) | 給工程師的技術詳解：五個技術層每一項技術的定位、參數、選型理由與踩過的坑，加上分析 pipeline 的逐步拆解。**這份是 HTML 不是 Markdown**，用瀏覽器開；類型／狀態標頭在頁首的 meta 列 |
| [`11-影片如何整理成文件.html`](11-影片如何整理成文件.html) | 「一部影片怎麼變成一份文件」的端到端拆解：四個階段的大架構，再逐一細到素材過濾、prompt 規則、落地與前端呈現。**HTML，用瀏覽器開**；主線不需要程式背景，程式碼與實測數字收在可展開區塊。片段怎麼來的請看 `10` |

## 開發歷程

| 文件 | 內容 |
|---|---|
| [`01-development-timeline.md`](01-development-timeline.md) | 依日期彙整的開發內容。持續追加新條目；`development-log.md`／`changelog/` 都已不存在，這是唯一的歷程記錄 |

## 執行紀錄

**仍在追加**（留在頂層）：

| 文件 | 記錄哪個任務 | 對應的原始需求 |
|---|---|---|
| [`05-web-ui-warm-redesign-plan.md`](05-web-ui-warm-redesign-plan.md) | UI 暖色改版（Phase 1–4 全完成）；**§8 是 UI 變更的持續紀錄**，每次調整都追加一條 | [`10`](prompts/10-web-ui-ux-warm-responsive-design.md) |
| [`09-畫面分析精細化計畫.md`](09-畫面分析精細化計畫.md) | 讓畫面描述更精細（P0–P4 完成，**P5 未開始**） | — |

**已結束**（收在 `archive/`，唯讀）：

| 文件 | 記錄哪個任務 | 對應的原始需求 |
|---|---|---|
| [`archive/09-web-ui-migration-plan.md`](archive/09-web-ui-migration-plan.md) | Tkinter → React + FastAPI 遷移（Phase 0–4 全完成） | [`08`](prompts/08-web-ui-migration-design.md) |
| [`archive/14-postgresql-migration-plan.md`](archive/14-postgresql-migration-plan.md) | SQLite → PostgreSQL 遷移（已完成） | — |
| [`archive/19-停格畫面問答功能計畫.md`](archive/19-停格畫面問答功能計畫.md) | 對停在某個時間點的畫面提問（已完成） | — |
| [`archive/07-ui-structure-and-features.md`](archive/07-ui-structure-and-features.md) | 已移除的 Tkinter UI 完整盤點。程式碼（`app.py`／`theme.py`／`ui/`）已於 Web UI 遷移 Phase 4 刪除，這份保留作為設計記錄 |

> `prompts/08 → archive/09`、`prompts/10 → 05` 是成對的：前者是還沒盤點程式碼前寫的規格草稿，
> 後者才是依真實現況推導、實際執行的計畫。**兩者有出入時一律以執行紀錄為準**。

## 原始需求 prompt（`prompts/`，唯讀原文）

| 文件 | 交付了什麼 |
|---|---|
| [`prompts/ui_prompt.md`](prompts/ui_prompt.md) | 最初的 Tkinter UI/UX 設計需求（含同目錄的 `UI_01~03.png` 截圖） |
| [`prompts/Claude_Code_Conversational_Video_Search_Prompt.md`](prompts/Claude_Code_Conversational_Video_Search_Prompt.md) | 對話式影片搜尋功能需求 |
| [`prompts/08-web-ui-migration-design.md`](prompts/08-web-ui-migration-design.md) | Web UI 遷移的設計規格草稿 |
| [`prompts/10-web-ui-ux-warm-responsive-design.md`](prompts/10-web-ui-ux-warm-responsive-design.md) | 暖色響應式 UI 的設計規格草稿 |

> 還有兩份原始 prompt（OCR 功能需求、搜尋準確率提升需求）**從未進過版控、目前不存在**。
> 它們的內容整理版保留在 [`00-overview.md`](00-overview.md) §2.2、§2.3。

## 簡報素材

| 文件 | 內容 |
|---|---|
| [`07-專題發表投影片說明.md`](07-專題發表投影片說明.md) | 專題發表投影片的架構說明與**每一個數字的出處對照表**；投影片本身是同資料夾的 HTML |

## 其他資產

| 路徑 | 內容 |
|---|---|
| `golden-set.csv` | 17 題固定查詢集，搜尋品質評測的基準 |
| `eval-runs/` | 歷次 Golden Set 評測結果（JSON），由 `scripts/run_golden_set_eval.py` 產生 |
| `prompts/UI_0*.png` | Tkinter 時期的介面截圖，原始需求的附件 |
| `refactor-board.html` | 歷次重構的任務看板（第三～五輪），含每張卡的驗證方式、刻意不做的理由，以及過程中被推翻的假設 |
| `pg-migration-board.html` | SQLite → PostgreSQL 遷移的階段看板 |
| `專題發表投影片*.html`／`*.pptx` | 專題發表投影片本體，說明見 `07`（同資料夾的 `10-*.html` 不是投影片，是技術文件） |

## 維護規則

1. **改程式碼時，只需要同步頂層的「現況參考」**。`archive/` 與 `prompts/` 是史料，不要回頭改寫——
   唯一的例外是**路徑指標**：檔案搬家時要跟著修，那不是改寫內容。
2. 事實變了要更新現況參考，但**不要刪掉舊決策**——加一段「後續變更」註記，保留演進脈絡
   （例如 `02` 裡 `BUDGET_USD` 從 $0.20 → $0.30 → $0.80 → $1.50 的記錄）。
3. 程式碼註解引用文件時寫**完整相對路徑加錨點**（例如
   `docs/02-technical-decisions.md#搜尋`）。曾經有 37 處註解指向從未存在的檔案，沒人發現——
   改完文件請跑一次檢查器，它會驗證所有連結與錨點（含 `archive/`、`prompts/` 子目錄，
   以及沒包成 markdown link 的裸引用）：

   ```bash
   uv run python scripts/check_doc_links.py
   ```
4. 新增文件時，開頭補上 `> **類型**：…｜**狀態**：…` 標頭，放進對應的目錄，並在這份索引登記一列。
5. **一件事的紀錄只放一個地方**。UI 變更寫進 `05 §8`（結構化：需求／修改／驗證），
   `01` 記那一天的敘事（發生什麼、推翻了什麼），兩者互相指過去；不要把同一段文字複製兩份。
