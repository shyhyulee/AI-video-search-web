# 對話式影片搜尋功能開發

請分析目前專案，將既有「單次關鍵字搜尋」擴充為「多輪對話式影片搜尋」。

## 1. 開發目標

使用者可透過自然語言搜尋影片，並在後續對話中：

- 增加或移除搜尋條件。
- 沿用上一輪的影片與搜尋結果。
- 使用「第二段」「剛才的結果」等指代表達。
- 指定影片、時間、人物、畫面文字或事件。
- 延長片段前後時間。
- 根據召回片段進行摘要與問答。
- 取得可播放的影片與正確時間點。

範例：

```text
使用者：找出有人進入生產線的畫面。
使用者：只看穿紅色衣服的人。
使用者：播放第二段，前後各延長十秒。
```

## 2. 設計原則

保留現有 Search Pipeline，不要由 LLM 直接搜尋資料庫或生成影片事實。

```text
聊天介面
→ Conversation Orchestrator
→ 對話狀態
→ Query Rewriter
→ Query Router
→ 現有 Hybrid Search
→ 時間片段合併與重排
→ Grounded Answer
```

責任區分：

- LLM：判斷意圖、改寫 Query、選擇搜尋方式、整理回答。
- Search Service：執行 ASR、VLM、OCR、Vector、BM25 與 Metadata 搜尋。
- Database：保存影片、Segment、搜尋結果與對話狀態。
- Answer Generator：只能依據召回片段回答，並提供影片與時間點。

## 3. 核心功能

### 對話意圖

至少支援：

```text
new_search
refine_search
select_result
expand_time_range
summarize_results
clarify
```

LLM 必須輸出結構化資料：

```json
{
  "action": "refine_search",
  "standalone_query": "穿紅色衣服的人進入生產線",
  "query_type": "person_event",
  "modalities": ["visual", "object"],
  "filters": {
    "video_ids": []
  },
  "selected_result_id": null,
  "requires_clarification": false
}
```

### 對話狀態

至少保存：

```text
conversation_id
active_query
active_filters
last_result_ids
selected_result_id
history_summary
```

不要每輪傳入完整對話；使用結構化狀態與摘要控制 Token。

### Search Service

將現有搜尋封裝成穩定介面：

```python
search_video_segments(
    query: str,
    query_type: str,
    modalities: list[str],
    video_ids: list[str] | None = None,
    start_time: float | None = None,
    end_time: float | None = None,
    top_k: int = 10,
)
```

LLM 不得自行產生 SQL、影片 ID、時間點或搜尋分數。

### 回傳內容

每筆結果至少包含：

```text
result_id
video_id
video_title
start_sec
end_sec
summary
thumbnail
evidence
score
```

`evidence` 應標示命中來源，例如 Transcript、Visual、OCR 或 Object Detection。

## 4. 開發階段

### Phase 0：架構盤點

先完成以下分析，不修改程式：

- 現有搜尋入口、資料流、資料表與 API。
- Segment、ASR、VLM、OCR 與 Embedding 結構。
- 可重用模組與需要修改的檔案。
- 對現有功能的影響與風險。
- 最小變更方案、測試與回滾策略。

請先輸出分析報告與實作計畫，等待確認後再開發。

### Phase 1：對話搜尋 POC

- 建立 Conversation API。
- 實作新搜尋與條件追問。
- 建立 Query Rewriter。
- 保存對話狀態與上一輪結果。
- 串接現有 Search Service。
- 回傳影片、時間點及命中證據。

### Phase 2：結果操作

- 支援「第一段」「上一個結果」等指代。
- 支援時間區間延長及 Metadata 篩選。
- 支援片段摘要及建議追問。
- 加入 No-answer 機制。

### Phase 3：進階搜尋

- Query Router 動態選擇 ASR、VLM、OCR 與 Detector。
- 複雜問題拆成多次搜尋。
- 資訊不足時提出澄清問題。
- 加入 Confidence、Reranking 與結果引用。

## 5. 驗收與限制

至少測試：

- 新搜尋與多輪條件追問。
- 指代解析及條件繼承、覆蓋。
- 時間區間操作。
- 無結果與錯誤輸入。
- 對話狀態隔離。
- 現有關鍵字搜尋 Regression Test。

評估指標：

```text
Intent Accuracy
Context Carryover Accuracy
Search Recall@K
Citation Accuracy
No-answer F1
Conversation Task Success Rate
P95 Latency
```

開發限制：

- 不破壞現有關鍵字搜尋功能。
- 不直接大幅重構既有 Pipeline。
- 所有修改必須具備測試與回滾方式。
- LLM 回答必須能追溯到實際影片片段。
- 沒有足夠搜尋證據時，必須明確表示找不到。
- 不確定現有設計時先標記問題，不要自行假設。

請先執行 Phase 0，輸出：

1. 現有架構分析。
2. 建議目標架構。
3. 需要新增或修改的檔案。
4. 資料模型與 API 設計。
5. 分階段實作順序。
6. 測試、風險與回滾方案。

等待確認後，再開始修改程式碼。
