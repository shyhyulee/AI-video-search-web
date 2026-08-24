# UI 暖色改版計畫與進度

## 1. 文件目的

`docs/10-web-ui-ux-warm-responsive-design.md` 是暖色響應式設計規格（含互動原型連結），要求「先分析現有
Frontend、API 與 UI 元件，再提出最小變更方案」。本文件的關係跟 `docs/08-web-ui-migration-design.md` 之於
`docs/09-web-ui-migration-plan.md` 一樣：`10` 是規格草稿，本文件才是**依現有程式碼實際盤點後推導、持續
更新**的執行計畫與進度紀錄。技術方向大致沿用 `10`（暖色 Token、響應式斷點、共用元件化這些主流選擇沒有
爭議），但元件拆分方式、套件選型、階段順序等細節多處依實測與專案既有慣例調整。

## 2. 背景與範圍

- Web UI 遷移（Tkinter → React + FastAPI，見 `docs/09-web-ui-migration-plan.md`）已完成並穩定，四個頁面
  （影片與分析／影片庫／搜尋結果／對話搜尋）功能與資料流完整。
- 這次是**純視覺／互動層美化**，明確不改動 `api/client.ts`／`api/types.ts`、後端、資料庫、搜尋或分析
  pipeline 邏輯。
- 硬性限制：刪除／搬移既有檔案前必須先問（CLAUDE.md）；每個階段結束都必須維持現有功能全部可用；沒有
  前端自動化測試套件，驗證方式＝`tsc -b --noEmit` + `oxlint`（零警告）+ `npm run build` + 對真實後端
  手動／自動化瀏覽器操作驗證。

## 3. 已確認的技術選型

| 決定點 | 選擇 | 理由 |
|---|---|---|
| 圖示 | 新增 `lucide-react` | 專案原本沒有圖示庫（`public/icons.svg` 是未使用的 Vite 腳手架殘留），新設計需要約 10–15 個圖示；純圖示資源零互動邏輯，跟先前拒絕 shadcn/ui 的理由（元件複雜度／無障礙行為）不衝突。 |
| ConfirmDialog／Toast | `ConfirmDialog` 用 `@radix-ui/react-dialog`；`Toast` 手刻 | Dialog 的 focus trap／Escape／焦點還原是無障礙最容易做錯的地方，用經過驗證的 headless 套件；Toast 沒有 focus trap、邏輯單純，手刻不多引入依賴。 |
| 字體 | 不加 Inter，`--font-sans` 開頭維持 `'Noto Sans TC'` | 原本沒有載入任何 Web Font；介面文字約 95% 是繁體中文，加 Inter 只影響數字／英文顯示，效益低於「零外部網路請求、本地優先」的一致性。 |
| 元件資料夾 | 維持扁平 `components/*.tsx`，不建 `layout/common/video/...` 子資料夾 | 既有 6 個元件檔案依規則不能為了分類而搬移；若只有新檔案分子資料夾會變成「半扁平半分類」，比全扁平更差。元件數量成長到約 24 個仍在合理範圍。 |
| 待分析清單「取消」 | 不做 | `src/ai_video_search_web/api/jobs.py` 只有 `GET /jobs`、`GET /jobs/{id}`、`POST /jobs/{id}/retry`，沒有 cancel endpoint；`docs/09` §3.2 當初提過 cancel 設計意圖但沒有實作成 API。這次不動後端，所以不做。 |

新增 npm 依賴僅兩個：`lucide-react`、`@radix-ui/react-dialog`。

## 4. Design Token

`frontend/src/index.css` 是唯一一份 CSS 檔案、Token 的唯一真實來源，本文件不重複貼色票，只記錄結構性
決定：

- 沿用既有 `--color-*` 命名慣例，直接把暖色系（陶土橘 `primary`／暖沙 `sand`／米白 `canvas`／`surface`）
  換上去，多數既有呼叫點（`bg-card`、`text-text-primary`…）零改動就吃到新色彩。
- 間距不需要新 token：Tailwind v4 預設 4px 刻度已完整覆蓋文件的 4/8/12/16/20/24/32px。
- 圓角只新增一個 `--radius-card`（18px，卡片用）；按鈕／輸入框的 10–12px、Badge 的 999px 已對應 Tailwind
  內建 `rounded-xl`／`rounded-full`。
- 新增一個低對比、ink 色調的 `--shadow-card`，取代 Tailwind 預設的純黑陰影，只用在 `elevated` 卡片。
- 重新定義 `--breakpoint-sm/md/lg`（560／900／1180px，對齊文件的響應式斷點表）取代 Tailwind 預設值——
  安全，因為全專案原本零個響應式 class。

## 5. 分階段實作與進度

延續文件 10 建議的 4 階段順序，但把「頁面內容重構」與「共用播放／結果元件抽取」的 Phase 3 拆成 3a／3b
兩步：Search／Conversation 都需要 `VideoPlayer`，且兩頁的影片 seek 邏輯是手刻、容易壞的部分，先求「抽出
元件、行為不變」再套新視覺，出問題時才分得出是哪一步造成的。

### Phase 1 — Design Token＋共用元件＋響應式外殼 ✅ 完成

**修改**：`index.css`（全新 `@theme` token）；`App.tsx`（`h-screen`→`h-dvh`；`<main>` 內容加
`max-w-[1540px] mx-auto`，並保留 `h-full` 維持每頁內部雙欄獨立捲動的高度鏈；Sidebar／內容依斷點呈現
完整／icon rail／隱藏三態；掛載 `ToastProvider`）；`Header.tsx`（改為品牌名＋當前頁面標題在左、精簡
`StatCard` 在右，窄螢幕漸進隱藏次要統計，避免大型 Stat Card 佔首屏）；`Sidebar.tsx`（rail 收合模式、
lucide 圖示、≤900px 隱藏改用新增的 `MobileBottomNav`）；`Badge.tsx`／`EmptyState.tsx`／`StatCard.tsx`／
`SimilarityBar.tsx`（改新色票、pill 圓角、`SimilarityBar` 順手修掉一處寫死的 `bg-[#E4E7EC]`）。

**新增元件**：`Button`（含 `IconButton`，`aria-label` 型別上必填）、`Card`、`SearchField`、`ErrorState`、
`LoadingSkeleton`、`ConfirmDialog`、`Toast`（context/hook 拆到 `lib/useToast.ts`，避免同檔案混合匯出
component 與 hook 觸發 `react/only-export-components`）、`MobileBottomNav`。

**驗證**：`tsc`／`oxlint`／`build` 全過；起 FastAPI＋Vite 用 Playwright 對四個路由做瀏覽器驗證——零
console error；背景色實測為新 token 值（非舊的藍灰）；1400px 顯示完整 Sidebar（240px）、1000px 收合成
icon rail（64px）、700px Sidebar 隱藏＋底部導覽正確出現；`document.body.scrollHeight` 四頁都精確等於
viewport 高度，確認 `max-w-[1540px]` 包裝層有正確延續 `h-full` 高度鏈、沒有把「內層獨立捲動」改壞成
「整頁捲動」。

### Phase 2 — 影片與分析、影片庫 ✅ 完成

**新增元件**：`VideoPoster`（縮圖，含載入失敗佔位；供清單小尺寸與詳細面板大尺寸共用）、`VideoListItem`
（縮圖＋標題＋可插槽 `meta`/`trailing`，取代密集 `<table>`）、`FilterChip`、`SegmentedControl`
（YouTube／本機來源切換，取代原本兩個輸入同時佔空間）、`Dropzone`（點擊或拖放選檔，上傳邏輯仍在
`api/client.ts` 的既有 XHR 進度機制）。

**修改**：`VideosPage.tsx`——來源改 Segmented Control；本機上傳改 Dropzone；待分析清單改
`VideoListItem`；「移除」改走 `ConfirmDialog`（取代 `window.confirm`）；分析中項目顯示 Stage＋Progress＋
Elapsed Time（`lib/format.ts` 新增 `formatElapsed`）；**額外把後端本來就有、但先前沒有任何 UI 呼叫點的
`retryJob`（`POST /jobs/{id}/retry`）接上**，失敗的分析工作現在有「重試」按鈕。`LibraryPage.tsx`——清單
改 `VideoListItem`；篩選按鈕換 `FilterChip`；選取列＝暖色底＋左側強調線；詳細面板套用 `VideoPoster`；
**新增明確的排序控制**（下拉選欄位＋圖示按鈕切換方向）取代原本點擊表格欄位標題排序（改成 list-item 後
不再有欄位標題可點）；三個操作按鈕依文件要求重新分出主從——「在此影片內搜尋」升級為 Primary，
「重新產生摘要」／「重新分析」維持 Secondary（原本三個視覺上是平等的）。

**驗證**：`tsc`／`oxlint`／`build` 全過；Playwright 針對高風險路徑做互動測試（非只看畫面）——勾選核取
方塊、點「移除」開出 `ConfirmDialog`、按「取消」後確認影片**沒有**被刪除（`videosPendingCountAfterCancelText`
跟按前一致）；篩選 chip 與排序下拉切換正確；點列表項目正確開出詳細面板；全程零 console error。

### Phase 3a — 抽取 VideoPlayer／SearchResultCard（先求行為不變）✅ 完成

**新增元件**：`VideoPlayer`（把 `SearchPage.tsx`／`ConversationPage.tsx` 各自內嵌、幾乎一模一樣的
`<video>`＋`onLoadedMetadata` seek 邏輯內化進元件本身：用 `useEffect` 依賴 `videoId`／`startSec`，
搭配一個 `loadedVideoId` ref 記錄「目前 DOM 上這顆 `<video>` 實際載入完成的是哪支影片」——同一支影片
內切換片段時直接 `currentTime` seek，不重新載入；換成不同影片時讓 `src` 變更觸發瀏覽器原生重新載入，
交給 `onLoadedMetadata` 處理。移除了「呼叫端必須記得寫 `key={video_id}`」這個兩頁都在用、容易忘記的
慣例）、`SearchResultCard`（取代兩頁複製貼上的 7 欄結果表格，這一步視覺維持接近原本的表格式排版，
只確保資訊與互動行為對等）。

**修改**：`SearchPage.tsx`／`ConversationPage.tsx` 套用這兩個新元件；因為 seek 邏輯搬進
`VideoPlayer`，`SearchPage` 原本的 `videoRef`／`selectResult` 手動判斷邏輯整個移除，改成單純
`setSelectedIndex`。

**驗證**：`tsc`／`oxlint`／`build` 全過。用真實搜尋（查詢「動物」）與真實對話搜尋測試最高風險的部分：
截取 `/api/v1/search` 的真實回應找出哪些結果共用同一支影片，點擊同影片的另一段時確認 `<video>` 的
`currentSrc` **沒有改變**（`srcUnchanged: true`）、只是直接 seek 到正確時間；初次點擊與換頁籤後重新
選取都確認影片正確載入並播放（`paused: false`）。全程零 console error。

### Phase 3b — 搜尋結果、對話搜尋視覺設計 ✅ 完成

**新增元件**：`EvidencePanel`（Search 頁專用；相似度＋字幕／畫面／OCR 三模態分數改成三欄格線，
「主要命中來源」用 `hit_source` 直接呈現人話說明取代原本三行分開的技術分數文字；Conversation 頁刻意
不用，沿用專案既有「對話搜尋不做完整分數面板」的設計選擇）、`ChatBubble`（使用者靠右陶土色底、助理
靠左暖沙色底）。`SearchResultCard` 新增 `featured` 版型（大版 Evidence Card：完整描述、
`SimilarityBar`、命中來源），供對話搜尋第一名結果使用，其餘結果與 Search 頁全部結果維持緊湊列表版型。
`Button`／`SearchField` 都新增 `lg` 尺寸選項（用 prop 而非 `className` 覆寫控制大小——兩個 Tailwind
utility 對同一個屬性〔例如 `h-10` 與 `h-12`〕同時出現在 class 字串裡，誰生效取決於 Tailwind 產生的
CSS 檔案內部順序、不是 class 字串裡的先後順序，是已知的不可靠寫法，這次全面改用 prop-based size）。

**修改**：`SearchPage.tsx`——查詢欄改用 `size="lg"` 的 `SearchField`＋`Button`；搜尋結果狀態列加上
用前端量測的搜尋耗時（`Date.now()` 前後差）；CSV 匯出改為 secondary `Button`；右側面板＝
`VideoPlayer`＋`EvidencePanel`；容器全面改用 `Card`。`ConversationPage.tsx`——訊息改用
`ChatBubble`；輸入框從 `<input>` 換成 `<textarea>`，Enter 送出、Shift+Enter 換行；初始狀態顯示 3 個
建議提示（重用 `FilterChip`，不傳 `active`，點擊直接送出訊息）；新增「已連接 N 支影片索引」狀態列
（重用 Header 已經在查的 `['stats']`，同一個 query key、不會多打一次 API）；新增「已檢索：字幕、OCR」
模態摘要（純前端從這一輪 `results[].hit_source` 字串〔例如「字幕＋畫面」「綜合」〕反推聯集，不需要
後端新欄位）；結果清單第一筆傳 `featured`。`lib/format.ts`——把 `SearchPage` 原本頁面內部的
`formatScore`（N/A fallback）搬進來供 `EvidencePanel` 共用。

**風險與踩到的坑**：
- `SearchField` 新增的 `size` prop 跟 `<input>` 原生 `size` 屬性（HTML 規格是數字，代表可視字元寬度）
  撞名，`tsc` 直接抓到型別錯誤，用 `Omit<InputHTMLAttributes<HTMLInputElement>, 'size'>` 排除原生
  屬性後解決。
- **Enter 送出對繁體中文輸入法是真實風險**：實作上用 `e.nativeEvent.isComposing` 判斷是否仍在
  注音／拼音組字狀態，組字中的 Enter（選字用）不能被誤判成送出。這次用 Playwright 手動 dispatch
  `CompositionEvent('compositionstart'/'compositionend')` 搭配帶 `isComposing` 旗標的 `KeyboardEvent`
  實測：組字中按 Enter 確認訊息數不變（被正確擋下），`compositionend` 後再按 Enter 才真的送出——不是
  只看程式碼邏輯，是真的模擬組字情境驗證過。
- 對話搜尋因為改用 `<textarea>`，`Shift+Enter` 換行行為也一併實測（`textarea.value` 確認含
  `\n`）。

**驗證**：`tsc`／`oxlint`／`build` 全過。實際搜尋＋對話測試：狀態列正確顯示「耗時 1.8 秒」；
`EvidencePanel` 分數格線正常渲染；`SearchField` 與搜尋 `Button` 量到的實際高度都是 48px（`lg` 尺寸
對齊，沒有前述的 class 覆寫順序問題）；建議提示點擊會直接送出且送出後從畫面消失；第一名結果確實用
`featured` 大版卡片呈現、內容包含完整描述與相似度條；「已檢索：字幕、OCR」正確彙整自真實回應的
`hit_source`。全程零 console error。

### Phase 4 — 響應式收合＋整體品質驗收 ✅ 完成

**響應式收合**：`LibraryPage.tsx`／`SearchPage.tsx`／`ConversationPage.tsx` 的主從版面
（`w-3/5`/`w-2/5`）改成 `flex flex-col gap-4 md:min-h-0 md:flex-1 md:flex-row`（≥900px 恢復現有的
固定高度＋左右並排＋各自 `overflow-auto` 獨立捲動；<900px 拿掉高度限制與 `overflow-auto`，兩塊直接
上下排列、跟著整頁走），純 CSS reflow、不做條件式掛載／卸載——這點特別重要，因為 React 元件樹不因
斷點改變，`<VideoPlayer>` 不會在縮放視窗跨越 900px 時被 remount，播放不會中斷。`ConversationPage`
的聊天面板另外加 `max-h-[70vh] md:h-3/5 md:max-h-none`，讓它在窄螢幕維持自己的獨立捲動（避免無限
長高把 Composer 推到很下面），跟主從版面的「跟著整頁捲動」策略不同，是刻意的差異化設計。
`SearchResultCard` 緊湊列表版型在 `sm`（560px）以下用 `hidden sm:inline` 隱藏相似度％與融合分數，
保留時間、來源、描述與可播放（選取）。

**跨元件品質稽核**（Phase 1–3 元件的補洞，不是重新設計）：
- `VideoListItem`／`SearchResultCard` 原本是純滑鼠 `onClick` 的 `<div>`，鍵盤完全無法操作——補上
  `role="button"`、`tabIndex={0}`、Enter／Space 觸發、可見 focus ring。
- `SegmentedControl` 原本用 `role="tablist"`/`"tab"`，但沒有對應的 `tabpanel`，語意不正確；改成
  `role="radiogroup"`/`"radio"` + `aria-checked`，更貼近實際「單選一個來源」的行為。
- `LoadingSkeleton`／`ErrorState` 是 Phase 1 就建好、但一直沒有接進任何頁面的元件——`VideosPage`／
  `LibraryPage` 的影片清單在資料載入中會落入 `!data || data.length===0` 這個判斷式，跟「真的沒有
  資料」共用同一個 `EmptyState`，導致每次進頁面都會先閃一下「目前沒有待分析影片／影片庫還沒有任何
  影片」再變成真正的清單。改用 `useQuery` 的 `isLoading`／`isError`／`refetch` 三個欄位，分開處理
  Loading（`LoadingSkeleton`）／Error（`ErrorState`＋重試）／Empty／有資料四種狀態。
- 所有頁面的狀態文字段落（下載／上傳狀態、搜尋狀態、對話狀態、摘要／重新分析狀態）補上
  `aria-live="polite"`。

**WCAG AA 對比度稽核**（實測發現的真實問題，不是預防性檢查）：Phase 1 規劃時對兩個 Badge 底色是
自行推導、當時只承諾「肉眼確認」，這次改用實際算法（WCAG 相對亮度公式）逐一算過所有「有色文字＋淺色
底」的組合，發現多處**低於** AA 一般文字門檻 4.5:1（Badge 文字本身是 12px 粗體，未達 WCAG 「大字」
定義的 14pt/18.66px 粗體門檻，所以套用的是 4.5:1 而非 3:1）：

| 組合 | 修正前 | 修正後 |
|---|---:|---:|
| 成功 Badge 文字 | 4.44:1 | 4.51:1 |
| 錯誤 Badge 文字（同時也是表單錯誤文字色） | 4.17:1 | 4.52:1 |
| 警告 Badge 文字（目前無呼叫點） | 2.00:1 | 4.51:1 |
| 白字在 Primary 按鈕／FilterChip／對話泡泡底色上 | 4.37:1 | 4.52:1 |
| 陶土色文字在淺色底上（Sidebar 選取態、Badge primary、SegmentedControl 選取態、對話搜尋第一名結果標籤、底部導覽選取態、「清除範圍」連結） | 3.55:1 | 5.10–6.17:1 |

修法：`--color-success`／`--color-error`／`--color-warning` 三個 token 各自小幅調暗（1–5%，`error`
以外肉眼幾乎看不出差異，`warning` 因為目前完全沒有呼叫點所以調整幅度較大也不影響任何畫面）；
`--color-primary` 調暗 2% 讓白字使用情境達標。**核心規則**：`--color-primary` 現在只用在「配白字的
實心背景」（按鈕、選取態 pill、對話泡泡），任何要在淺色背景上直接當文字色用的地方一律改用既有的
`--color-primary-hover`（本來就是給 hover 用的深色，剛好也達標，不必新增 token）——全專案 grep 過，
6 處這樣用 `text-primary` 的地方全部改掉。範圍**明確排除**：只做文字對比度，UI 元件邊框／圖示等
「非文字對比」（WCAG 1.4.11，門檻 3:1）沒有逐項稽核，留待之後需要時再補。

**驗證**：`tsc`／`oxlint`／`build` 全過。用 Playwright 掃描 6 個寬度（1920/1536/1366/1180/900/560）
×4 個頁面共 24 種組合，全部零水平溢位；確認 Sidebar 三態（≥1180px 完整 240px／900–1180px icon rail
64px／<900px 隱藏＋底部導覽）在各寬度正確對應；確認 560px 時三個主從頁面的兩塊面板真的垂直堆疊（用
兩塊面板的 bounding box 上下關係量測，不是只看程式碼）；**關鍵回歸測試**：對真實搜尋結果選取播放後，
把視窗從 1400px 縮到 700px 再放回 1400px（跨越 900px 斷點兩次），確認 `<video>` 的 `currentSrc`
全程不變、`currentTime` 持續前進而非歸零——證實純 CSS reflow 沒有把播放中的元件 remount 掉；鍵盤
Tab 到 `VideoListItem`、按 Enter 觸發選取，確認可行。對比度修正後另外截圖比對，色彩改動在正常瀏覽下
無法用肉眼分辨差異，沒有視覺回歸。全程零 console error。

## 6. 驗收結果

對照 `docs/10-web-ui-ux-warm-responsive-design.md` §11 的驗收標準逐項回報，區分「已用工具實測確認」
與「設計上已處理、但沒有做窮舉式量測」，不把後者寫成前者：

**已實測確認**：
- 四個頁面視覺與操作一致（統一 Design Token、共用元件庫）。
- 1366×768、14 吋筆電首屏看得到主要操作與部分結果（截圖確認）。
- ≤1180px Sidebar 正確收合成 icon rail，≤900px 隱藏改底部導覽（6 寬度 × 4 頁面量測）。
- ≤900px 主從版面正確改為單欄（量測兩塊面板的 bounding box 上下關係）。
- ≤560px 無水平溢位（24 種寬度×頁面組合全數確認）；搜尋結果卡片正確隱藏次要分數、保留時間/來源/
  描述/可播放。
- 影片上傳（XHR 進度）、YouTube 下載、分析（含新接上的重試）、刪除（`ConfirmDialog` 取消路徑不誤刪）
  功能正常。
- 影片庫篩選、排序（新排序控制）、摘要重新產生、重新分析功能正常。
- 搜尋結果、三模態分數、時間點、CSV 功能保持一致；`EvidencePanel` 正確顯示真實資料。
- 對話搜尋能保存多輪 context、播放正確片段、IME 組字狀態下 Enter 不誤送出（實際 dispatch
  `CompositionEvent` 測試過）。
- HTML5 Video 由 `start_sec` 正確播放；縮放跨斷點不中斷播放（真實搜尋結果實測）。
- Loading／Empty／Error／Selected State 有實際串接（`LoadingSkeleton`／`ErrorState` 補接、
  Selected 態用 border+底色雙重標示不只靠顏色）。
- 鍵盤操作：新增的可點擊 `<div>`（`VideoListItem`／`SearchResultCard`）補上 Tab／Enter／Space；
  文字對比度用 WCAG 公式逐一算過並修正到 AA 4.5:1（見 Phase 4 記錄的對照表）。
- 原有 API、Pipeline、資料庫行為未被觸碰（這次規劃與實作全程沒有修改 `api/client.ts` 型別以外的
  後端／資料庫程式碼）。

**設計上已處理、未窮舉量測（誠實揭露，不算完整驗收）**：
- WCAG AA 只做了文字對比度，UI 元件邊框／圖示等非文字對比（1.4.11，門檻 3:1）沒有逐項算過。
- 沒有用真正的螢幕報讀軟體（NVDA／VoiceOver）走過一輪，`aria-live`／`role`／`aria-label` 是依規範
  正確性檢查，不是端到端可用性測試。
- Disabled／Processing 狀態視覺上都有處理（按鈕 `disabled:opacity-40`、忙碌態文字），但沒有像
  Loading／Error 那樣做系統性盤點，可能有漏網的個案。
- `prefers-reduced-motion` 只在 Phase 1 加了全域 CSS 規則，沒有針對每個有動畫的元件個別測試套用
  效果。

## 7. 明確排除、不在這次處理

- 待分析清單「取消」（見上，後端無對應 API）。
- 跨頁籤 job 追蹤狀態遺失（`docs/09` §9 已記錄的已知架構缺口，是狀態管理問題不是視覺問題）。
- 「處理紀錄」頁籤、`GET /search/recent` 前端——原本 Web 遷移就刻意不做，文件 10 也沒要求恢復。
- 前端自動化測試（Playwright）——這次每個階段都用 Playwright 手動跑過關鍵互動路徑，但沒有把測試腳本
  提交進 repo；值得做，但屬於測試基礎建設投資，不是這次美化的範圍。
