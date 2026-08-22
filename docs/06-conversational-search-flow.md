# 對話式影片搜尋 — 目前流程與邏輯

Phase 1 實作完成後的現況說明，對應原始需求 [`Claude_Code_Conversational_Video_Search_Prompt.md`](Claude_Code_Conversational_Video_Search_Prompt.md) 與規劃時的分階段安排。目標是讓之後接手的人（人類或 AI Coding Agent）不用重讀程式碼就能掌握現在對話搜尋實際怎麼運作、哪些是刻意留到 Phase 2／3 才做。

## 1. 一句話總覽

使用者在「對話搜尋」頁籤打字 → LLM 只負責判斷「這句話想做什麼、要用什麼查詢字串去搜」→ 真正的搜尋動作 100% 交給既有的 `search.search()`（Hybrid RRF，邏輯完全沒改）→ 結果與回覆文字顯示回 UI，並把這輪的狀態存回頁籤實例（記憶體，不落地資料庫），供下一輪對話使用。

## 2. 整體流程

```text
使用者在「對話搜尋」頁籤輸入一句話（ui/conversation_tab.py）
        │  背景執行緒起工，避免卡住 Tkinter 主執行緒
        ▼
pipeline/conversation.py :: handle_turn(state, user_message)
        │
        ├─ 1) 呼叫 pipeline/intent.py :: classify_intent()
        │     → LLM（gpt-4o-mini，structured output）判斷這句話是四種
        │       意圖（action）的哪一種，並把它改寫成一句「不靠上下文
        │       也看得懂」的 standalone_query
        │
        ├─ 2) 依 action 分派到三條路徑之一：
        │     a. clarify／requires_clarification → 不搜尋，直接反問
        │     b. select_result                    → 不搜尋，從上一輪
        │        結果清單挑一筆
        │     c. new_search／refine_search         → 呼叫既有
        │        search.search()（Hybrid RRF，邏輯完全沒動）
        │
        └─ 3) 組裝 ConversationTurnResult（回覆文字＋結果清單＋花費＋
              新的 ConversationState），回傳給 UI
                ▼
UI 更新聊天訊息串＋結果 Treeview＋把新狀態存回 self._state
```

## 3. 逐步說明

### ① UI 層（`ui/conversation_tab.py`）

使用者按送出後，沿用既有「搜尋結果」頁籤（`ui/search_tab.py`）一模一樣的模式：背景執行緒呼叫 `handle_turn()`、結果丟進 `queue.Queue`、`self.after(150, poll)` 輪詢，避免卡住 Tkinter 主執行緒。頁籤實例自己持有 `self._state`（一個 `ConversationState`），每輪結束後用 `turn.new_state` 覆蓋掉它——**這就是整個對話的記憶體**，不寫資料庫，App 關掉就重置。

### ② 意圖判斷（`pipeline/intent.py :: classify_intent()`）

把「歷史摘要」「上一輪結果清單（含編號、影片名、時間、描述）」「使用者這句話」一起塞進一個 prompt，用 `chat.completions.parse` 拿結構化輸出（跟 `translation.py` 同一套機制）。LLM 只回傳五類欄位：

- `action`：`new_search`／`refine_search`／`select_result`／`clarify` 四選一
- `standalone_query`：改寫後的獨立查詢句
- `filters_video_ids`：使用者有沒有明講要限定在哪支影片
- `selected_result_index`：選第幾個結果（1-based，對應清單上顯示的編號）
- `requires_clarification`／`clarification_question`：看不懂時的反問

LLM 完全碰不到資料庫、不會自己編影片 ID 或時間點——這是規劃時的責任區分限制，見原始 prompt 文件「LLM：判斷意圖、改寫 Query；Search Service：執行搜尋」。

### ③ 三條分派路徑（`pipeline/conversation.py`）

| action | 邏輯 | 會不會呼叫 `search()` |
|---|---|---|
| `clarify` 或 `requires_clarification=True` | 直接把 `clarification_question` 當回覆，結果清單維持顯示上一輪的（不清空） | 不會 |
| `select_result` | 檢查 index 是否落在 `1..len(last_results)`；有效就取 `last_results[index-1]` 當 `selected_result`，回傳只有這一筆的結果清單；index 無效或根本沒有上一輪結果，就退回反問「不確定指的是哪一個」 | 不會 |
| `new_search`／`refine_search` | 解析要不要帶影片篩選（見下），呼叫 `search.search(standalone_query, video_id=...)`，用規則模板組回覆文字 | 會 |

### ④ 篩選條件沿用邏輯（`_resolve_video_ids()`）

- LLM 這輪明講了 `filters_video_ids` → 直接用（覆蓋）
- 沒明講，但 action 是 `refine_search` → 沿用上一輪 `state.active_filters["video_ids"]`
- 沒明講，且 action 是 `new_search` → 清空，視為換題目

**已知落差**：`search.search()` 目前只吃單一 `video_id: int | None`，不是清單。就算 `video_ids` 解析出多個，`_handle_search()` 也只會取第一個（`video_ids[0]`），其餘被忽略——這是規劃時就標記過的 Phase 3 範圍（Query Router 才會真的支援多影片／依模態篩選）。

### ⑤ 回覆文字（`_build_reply_text()`）

純規則模板，不是 LLM 生成：沒結果就明講「沒有找到足夠相關的片段」；有結果但 `is_confident=False`（沒有被 BM25/LIKE 印證）就加「把握度較低」前綴；否則只回「找到 N 個相關片段」。**這是 Phase 1 刻意簡化的地方**——原始需求要的「Grounded Answer（LLM 摘要＋引用）」還沒做，現在只列清單不生成摘要文字。

### ⑥ 歷史摘要（`_append_history()`）

不額外呼叫 LLM 摘要（省成本），純字串規則：每輪把「使用者說了什麼→做了什麼」append 成一行，超過 `_HISTORY_MAX_CHARS`（800 字元）就從最舊的一行開始砍掉，餵給下一輪 `classify_intent()` 當 `history_summary`。

## 4. 每輪實際的 API 呼叫量（跟成本有關）

- `clarify` / `select_result`：只有 1 次 LLM 呼叫（意圖判斷）。
- `new_search` / `refine_search`：意圖判斷 1 次 ＋ `search.search()` 內部（查詢翻譯 1 次＋中英文最多 3 次 embedding，全域搜尋還可能疊加影片層級篩選的 embedding，但標題／摘要有記憶體快取，見 `search.py::_embed_cached()`）。

這個成本疊加**沒有上限或警示**——延續既有搜尋本來就有的缺口（見 [`05-known-limitations-and-open-items.md`](05-known-limitations-and-open-items.md)），對話模式會讓每輪呼叫次數更多，是規劃時已經跟使用者確認過、刻意列為已知風險、Phase 1 沒有處理的部分。

## 5. 資料模型

```python
# pipeline/conversation.py（記憶體 dataclass，不落地 DB）
@dataclass
class ConversationState:
    active_query: str | None = None
    active_filters: dict = field(default_factory=dict)   # 目前只用 {"video_ids": list[int]}
    last_results: list[SearchResult] = field(default_factory=list)
    selected_result: SearchResult | None = None
    history_summary: str = ""
```

不需要 `conversation_id`：一個 `ConversationTab` 頁籤實例就是一個對話，App 內同時只有一個對話視窗，沒有多 session 併發或跨裝置同步需求（單機單人 Tkinter 桌面 App）。跟 `search.py::_title_summary_embedding_cache` 是同一種「行程存活期記憶體狀態」的設計先例。

`search.SearchResult` 為了讓對話能跨輪次穩定引用同一個片段，新增了 `segment_id: int`（對應 `db.SegmentRecord.id`），這是這次唯一動到既有搜尋核心 dataclass 的地方，排序／融合邏輯本身沒有變動。

## 6. 目前範圍內 vs 範圍外

**已做（Phase 1）：** 四種意圖分派、獨立查詢改寫、指代解析（選上一輪第 N 個結果）、條件沿用/覆蓋、無結果／低把握度的明確提示。

**還沒做（規劃時就標記給 Phase 2／3，非實作遺漏）：**

- `expand_time_range`（「前後延長十秒」）、`summarize_results`（片段摘要問答）
- 真正的 LLM Grounded Answer（現在只有規則模板組回覆文字）
- 多影片同時篩選、依 modalities 動態選擇搜尋方式（Query Router）
- 對話成本護欄、對話狀態落地資料庫

## 7. 相關檔案

| 檔案 | 角色 |
|---|---|
| `ui/conversation_tab.py` | 「對話搜尋」頁籤：訊息串、輸入框、結果列表 |
| `pipeline/conversation.py` | Conversation Orchestrator：`ConversationState`／`handle_turn()` |
| `pipeline/intent.py` | 意圖判斷與 Query Rewriter：`classify_intent()` |
| `pipeline/search.py` | 既有 Hybrid Search（未改動排序邏輯，只加 `segment_id` 欄位） |
| `ui/playback.py` | 從 `search_tab.py` 抽出的共用片段播放邏輯，兩個頁籤共用 |
| `tests/test_conversation.py`／`tests/test_intent.py` | 對應的純邏輯測試（mock LLM／搜尋，不呼叫真實 API） |
