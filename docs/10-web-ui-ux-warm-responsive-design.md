# 影尋 AI — Web UI/UX 暖色響應式設計與開發規格

> 本文件供 Claude Code 閱讀與執行。請先分析現有 Frontend、API 與 UI 元件，再提出最小變更方案；取得確認後才開始修改程式碼。

## 1. 任務目標

依照現有四個頁籤重新設計 Web UI：

1. 影片與分析。
2. 影片庫。
3. 搜尋結果。
4. 對話搜尋。

設計目標：

- 建立一致、專業且適合長時間操作的企業級 AI 工作台。
- 使用暖色系取代目前以冷色與藍色為主的視覺。
- 主要支援 14 吋筆電與桌機螢幕，同時能適應平板與窄畫面。
- 改善資料密度、表格可讀性、操作層級與跨頁面一致性。
- 保留既有功能、資料流、API 與影片搜尋邏輯。
- Web UI 穩定前不得移除或破壞現有功能。

互動原型：

<https://video-search-warm-ui.shyhyulee.chatgpt.site>

原型用於確認視覺方向與資訊架構；實作時必須對接現有專案資料與 API，不得直接照搬假資料。

## 2. 核心 UX 原則

### 2.1 工作台優先

- 第一個畫面直接呈現主要操作與資料，不放行銷式 Hero。
- 頁面標題簡短，說明文字不超過兩行。
- 一個區塊只保留一個 Primary Action。
- 危險操作使用低強度樣式，並在執行前再次確認。

### 2.2 主從式資訊架構

影片庫、搜尋結果與對話搜尋使用：

```text
左側：清單、搜尋結果或對話
右側：影片預覽、詳細資料或檢索證據
```

桌機與 14 吋筆電保留雙欄；窄畫面改為上下排列。

### 2.3 Evidence-first

所有搜尋結果與 AI 回答應顯示：

- 影片名稱。
- 開始與結束時間。
- 命中來源：字幕、畫面、OCR。
- 相似度或融合分數。
- 可直接播放片段的操作。

### 2.4 狀態完整

所有頁面與元件必須處理：

```text
Loading
Empty
Success
Error
Disabled
Selected
Processing
```

不可只設計成功狀態。

## 3. Design System

### 3.1 品牌與文字

```text
產品名稱：影尋 AI
一句話：用一句話，找到影片裡的關鍵時刻。
輔助文案：找到，不必看完。
```

### 3.2 顏色 Token

請使用 CSS Variables 或 Tailwind Theme 集中管理，不要在元件中散落 Hex Color。

```css
:root {
  --color-ink: #34241d;
  --color-muted: #796b63;
  --color-muted-light: #a39388;

  --color-canvas: #f8f3ed;
  --color-surface: #fffdf9;
  --color-surface-secondary: #fbf6ef;

  --color-sand: #f1e4d5;
  --color-sand-dark: #e9d5c0;
  --color-border: #eadfd4;

  --color-primary: #bd5d42;
  --color-primary-hover: #9d4630;
  --color-primary-soft: #f7e4dc;

  --color-accent: #dc9a3c;
  --color-success: #617258;
  --color-success-soft: #e8f0e4;
  --color-danger: #b6483b;
}
```

顏色使用規則：

- 陶土橘只用於主要操作、選取狀態與重要數值。
- 暖沙色作為背景與區塊層次，不作為主要文字色。
- 成功、警告與錯誤狀態必須同時包含文字或 Icon，不可只靠顏色。
- 文字與背景需達到 WCAG AA 對比度。

### 3.3 字體與層級

推薦 Font Stack：

```css
font-family:
  Inter,
  "Noto Sans TC",
  "Microsoft JhengHei",
  system-ui,
  sans-serif;
```

| 層級 | 建議尺寸 | 用途 |
|---|---:|---|
| Page Title | 26–34px | 頁面主標題 |
| Section Title | 17–20px | 卡片與區塊標題 |
| Body | 14–15px | 主要內容 |
| Secondary | 12–13px | Metadata、說明 |
| Caption | 10–11px | Badge、時間、輔助資訊 |

### 3.4 間距、圓角與陰影

- 採用 `4 / 8 / 12 / 16 / 20 / 24 / 32px` 間距系統。
- 卡片圓角：`16–18px`。
- Input、Button 圓角：`10–12px`。
- Badge 圓角：`999px`。
- 陰影應低對比，只用於浮起的主要卡片與 Sticky Panel。
- 相鄰資料列以 Border 分隔，避免每列都使用厚重卡片。

## 4. 全域 Layout

### 4.1 桌機與 14 吋筆電

```text
左側 Sidebar
＋ Top Header
＋ Content Workspace
```

Sidebar：

- 完整桌機寬度約 `240px`。
- 顯示品牌、四個主要功能與 AI 服務狀態。
- Active Item 使用暖粉背景、陶土色文字與明確選取標記。

Top Header：

- 左側顯示 Breadcrumb。
- 右側顯示待分析、已分析、片段數及累計成本。
- 統計資訊保持精簡，不使用大型 Stat Card 佔據首屏。

Content：

- 最大寬度約 `1540px`，大螢幕置中。
- 14 吋筆電降低水平 Padding，優先保留內容空間。
- 每頁第一個 Viewport 必須看得到主要操作與部分結果。

### 4.2 響應式斷點

| 畫面寬度 | 版面行為 |
|---|---|
| `> 1180px` | 完整 Sidebar、雙欄主從版面 |
| `901–1180px` | Sidebar 收合為 Icon Rail，保留雙欄 |
| `≤ 900px` | 隱藏 Sidebar、改用底部導覽、主從版面改單欄 |
| `≤ 560px` | Button 滿版、Filter 可橫向捲動、次要欄位隱藏 |

高度設計：

- 以 `100dvh` 或等價方式處理可視高度。
- Header、播放器與詳細面板可 Sticky，但避免產生兩層互相衝突的 Scroll。
- 14 吋筆電常見高度約 700–800px，頁面不可依賴大量垂直留白。

## 5. 共用元件

優先建立以下共用元件：

```text
AppShell
Sidebar
TopHeader
MobileBottomNavigation
PageHeading
PrimaryButton
SecondaryButton
IconButton
StatusBadge
FilterChip
SearchField
VideoPoster
VideoPlayer
VideoListItem
SearchResultCard
SimilarityIndicator
EvidencePanel
EmptyState
ErrorState
LoadingSkeleton
ConfirmDialog
Toast
```

規則：

- 不要在四個頁面重複實作播放器、搜尋列、Badge 或 Result Card。
- 使用語意化元件名稱，不要以顏色命名，例如避免 `BlueButton`。
- 共用元件提供 Loading、Disabled、Selected 與 Error 狀態。
- 按鈕及可點擊區域至少 `40×40px`。
- 所有 Icon Button 必須有 `aria-label`。

## 6. 頁面設計

### 6.1 影片與分析

目標：快速加入影片並清楚管理待處理任務。

版面：

```text
Page Heading
├── 影片來源卡片
│   ├── YouTube 網址
│   └── 本機影片
├── 分析建議卡片
└── 待分析影片清單
```

要求：

- YouTube 與本機影片使用 Segmented Control 切換，不同來源不要同時佔據大量空間。
- YouTube 輸入包含 URL、取得影片按鈕與格式提示。
- 本機上傳使用 Dropzone，支援點擊與拖放。
- 待分析清單顯示縮圖、名稱、來源、加入時間、長度與狀態。
- 多選後顯示「開始分析」與「移除」。
- 分析中的影片顯示 Stage、Progress、Elapsed Time 與取消／重試操作。
- 刪除使用 Confirm Dialog，不可只依賴 Browser Confirm。

14 吋筆電：

- 清單採緊湊 Row，不建立大面積空白表格。
- 優先保留影片名稱與狀態，次要欄位可隱藏。

### 6.2 影片庫

目標：快速掃描影片並查看摘要與索引完整度。

桌機版面：

```text
搜尋與 Filter Toolbar
├── 左：影片清單
└── 右：影片詳細資料
```

影片清單：

- 使用縮圖＋標題＋Metadata 的 List Item，取代欄位過密的傳統表格。
- 顯示影片長度、片段數、分析時間、成本與狀態。
- Filter Chip：全部、分析完成、分析失敗、無字幕、純畫面。
- Active Row 使用淡暖色背景與左側選取線。

詳細面板：

- 影片預覽置頂。
- 顯示標題、長度、片段數、分析時間與成本。
- 顯示字幕、畫面描述、OCR 的完整度 Badge。
- AI 摘要使用舒適行高，避免過寬文字行。
- Primary Action：在此影片內搜尋。
- Secondary Action：重新產生摘要、重新分析。

響應式：

- `≤ 900px` 改為清單在上、詳細資料在下。
- 可選擇使用 Drawer 顯示詳細內容，但不可失去返回清單的方式。

### 6.3 搜尋結果

目標：讓使用者快速判斷「哪個片段最相關」及「為什麼命中」。

搜尋區：

- 使用大型自然語言搜尋欄。
- 顯示結果數、搜尋耗時與作用中的 Filter。
- CSV 匯出為 Secondary Action。

結果區：

- 使用 Search Result Card，不使用過多欄位的資料表。
- 每張卡片顯示排名、時間、來源、片段描述、融合分數及相似度。
- 使用者選取結果時，右側更新播放器與 Evidence Panel。
- 相似度必須同時顯示數字與視覺指示器。

Evidence Panel：

- 顯示最終相似度。
- 顯示字幕、畫面與 OCR 分數。
- 說明主要命中原因。
- 提供「從時間點播放」Primary Action。

響應式：

- `≤ 900px` 結果列表與播放器上下排列。
- `≤ 560px` 隱藏次要分數，但保留時間、來源、描述與播放。

### 6.4 對話搜尋

目標：用多輪對話逐步縮小影片片段範圍。

桌機版面：

```text
左：對話訊息流
右：本輪檢索結果與播放器
```

對話區：

- Assistant 與 User 使用不同 Bubble 樣式與對齊。
- Composer 固定在對話面板底部。
- 支援 `Enter` 送出與 `Shift + Enter` 換行。
- 初始狀態提供 2–3 個 Suggested Prompt。
- 顯示目前是否連接影片索引。
- 回答中標示已檢索哪些模態。

本輪結果：

- 第一名結果使用大型 Evidence Card。
- 其他結果使用緊湊清單。
- 每筆結果顯示時間、來源與相似度。
- 必須能直接播放並保持對話上下文。

響應式：

- `≤ 900px` 對話在上、結果在下。
- Composer 不可遮住訊息或底部導覽。
- 窄畫面需確保輸入區與送出按鈕容易操作。

## 7. Interaction 與 Feedback

### 7.1 搜尋

```text
輸入 Query
→ 顯示 Loading
→ 顯示結果數與耗時
→ 自動選取第一筆
→ 右側顯示播放器與命中證據
```

### 7.2 分析任務

```text
queued
→ downloading／uploading
→ extracting_audio
→ asr
→ scene_analysis
→ vlm／ocr
→ embedding
→ indexing
→ completed／failed
```

前端顯示使用者可理解的中文 Stage，不直接顯示內部 Enum。

### 7.3 錯誤

- 表單錯誤顯示在欄位附近。
- API 錯誤使用 Toast 或 Inline Error。
- 失敗任務保留錯誤摘要與重試操作。
- 技術 traceback 不應直接顯示給一般使用者。

## 8. Accessibility

- 所有 Input 具備可見 Label 或明確 `aria-label`。
- 鍵盤可以操作 Navigation、Filter、列表、Dialog 與播放器。
- Focus Ring 不可被移除。
- 選取狀態不可只依賴背景顏色。
- 表格或 List Item 需有合理的語意結構。
- 動畫遵守 `prefers-reduced-motion`。
- Loading 狀態適當使用 `aria-live` 或 `aria-busy`。

## 9. 建議前端結構

請依現有 Framework 調整，不要未分析就更換技術棧。

```text
frontend/src/
├── app/
├── components/
│   ├── layout/
│   ├── common/
│   ├── video/
│   ├── search/
│   └── conversation/
├── features/
│   ├── upload/
│   ├── library/
│   ├── search/
│   └── conversation/
├── api/
├── hooks/
├── styles/
└── types/
```

狀態原則：

- API Server State 使用既有 Query Library；若未採用，可評估 TanStack Query。
- Local UI State 保留在頁面或 Feature 內。
- 不使用全域 State 保存可由 API 重取的資料。
- Conversation State 與 Job State 必須能在重新整理後恢復。

## 10. 開發階段

### Phase 0：盤點，不修改程式

請先輸出：

1. 現有 Frontend 技術棧、Routing 與元件結構。
2. 四頁與 API 的實際資料流。
3. 可直接重用與需要重構的元件。
4. 現有 CSS、Design Token 與響應式規則。
5. 建議新增或修改的檔案清單。
6. 對既有功能的風險與回滾方法。

### Phase 1：Design System 與 App Shell

- 建立 Color、Typography、Spacing、Radius、Shadow Token。
- 建立 Sidebar、Top Header、Mobile Navigation。
- 建立 Button、Badge、Input、Card、Dialog、Toast。
- 保留現有 Route 與 API 行為。

### Phase 2：影片與分析、影片庫

- 先完成上傳、任務進度與影片管理。
- 再完成主從式影片庫與詳細面板。
- 驗證上傳、刪除、重新分析與摘要功能。

### Phase 3：搜尋結果、對話搜尋

- 建立共用 Search Result Card、Video Player 與 Evidence Panel。
- 對接單次搜尋與多輪 Conversation State。
- 驗證時間點跳轉、Filter、CSV 與 No-answer。

### Phase 4：響應式與品質驗證

- 驗證 `1440×900`、`1366×768`、`1024×768`、`900px` 與 `560px`。
- 驗證鍵盤操作、Focus、Loading、Empty、Error 與 Disabled State。
- 執行既有 Regression Test。
- 確認後才移除已不使用的舊 UI 程式。

## 11. 驗收標準

- 四個頁面視覺與操作一致。
- 1366×768 畫面無主要操作被裁切。
- 14 吋筆電首屏可看到主要操作與部分結果。
- `≤ 1180px` Sidebar 正確收合。
- `≤ 900px` 主從版面正確改為單欄。
- `≤ 560px` 無不可操作的擁擠欄位或水平溢位。
- 影片上傳、YouTube 下載、分析、刪除與重試功能正常。
- 影片庫篩選、排序、摘要及重新分析功能正常。
- 搜尋結果、分數、時間點與 CSV 功能保持一致。
- 對話搜尋能保存上下文並播放正確片段。
- HTML5 Video 能由 `start_sec` 正確播放。
- Loading、Empty、Error、Disabled 與 Selected State 完整。
- 鍵盤操作及基本 WCAG AA 檢查通過。
- 原有 API、Pipeline 與資料庫行為不被破壞。

## 12. Claude Code 首次執行指令

第一階段只分析，不修改 Frontend、Backend、Database 或文件。

請閱讀：

- 現有四頁 Frontend 程式。
- 共用 Layout、Component、CSS 與 Theme。
- API Client、Type、State Management。
- 影片播放、任務進度、搜尋與 Conversation 相關程式。
- 既有測試。

完成後回報：

1. 文件要求與實際程式的差異。
2. 元件與頁面重構方案。
3. Responsive Layout 實作方式。
4. Design Token 與共用元件清單。
5. 分階段修改檔案與測試清單。
6. 風險、相容性與回滾方案。

遇到不確定資訊請標記為「待確認」，不要自行假設。等待確認後，再開始 Phase 1。
