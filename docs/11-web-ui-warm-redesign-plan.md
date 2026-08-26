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
  ——**後續已在 8.3 用 keep-alive 處理掉根因**（頁籤不再卸載），這裡保留原判斷作為當時的範圍紀錄。
- 「處理紀錄」頁籤、`GET /search/recent` 前端——原本 Web 遷移就刻意不做，文件 10 也沒要求恢復。
- 前端自動化測試（Playwright）——這次每個階段都用 Playwright 手動跑過關鍵互動路徑，但沒有把測試腳本
  提交進 repo；值得做，但屬於測試基礎建設投資，不是這次美化的範圍。

## 8. 後續調整記錄

Phase 1–4（上面章節）完成並驗收後，使用者陸續提出的小幅調整記錄在這裡，不回頭改動上面的階段紀錄。

### 8.1 對話搜尋改左右並排（2026-08-24）

**問題**：`ConversationPage` 從 Phase 1 到 Phase 4 全程維持「對話在上、結果在下」的上下排列，這其實
是沿用最早 Tkinter 版（`PanedWindow` 垂直分割）就有的版面，Phase 1–4 只做了視覺重新設計，沒有重新
檢視版面本身。但文件 10 §6.4 桌機版面原文明確寫的是「左：對話訊息流；右：本輪檢索結果與播放器」，
跟實際做出來的上下排列不一致——這個落差在 Phase 3b／4 撰寫實作紀錄時都沒有發現，是這次使用者直接
指出來才處理的。

**修改**：只動 `ConversationPage.tsx` 一個檔案。桌機（`md:` 即 ≥900px）改成 `md:flex-row`：左欄
（`md:w-3/5`，跟全站其他主從版面的比例一致）放對話面板，維持原本 `max-h-[70vh] md:max-h-none` 的
高度處理，讓面板在兩種版面下都正確撐滿；右欄（`md:w-2/5`）改成上下兩塊——播放器在上（自然高度）、
「這一輪的相關片段」清單在下（`md:flex-1 md:overflow-auto`，自己捲動）。≤900px 拿掉 `md:flex-row`
後自動退回原本的上下排列，對齊文件 10 的響應式規則本身就要求「≤900px 對話在上、結果在下」——這點
不需要額外處理，是 `flex-col md:flex-row` 這個既有 pattern 的自然結果。另外把兩處寫死方位的文案
（播放器空狀態「點選左方片段即可播放」、結果清單空狀態「在上方輸入想找的內容開始對話」）改成不依賴
版面方向的措辭（「尚未選取片段」「開始對話以取得相關片段」），避免版面之後再調整時文字又跟畫面對不
上。

**驗證**：`tsc`／`oxlint`／`build` 全過。實際送出真實訊息、選取結果，確認播放器正確播放（真實
`currentTime` 前進、非暫停）；量測 `.rounded-card` 區塊的 bounding box 確認桌機下對話面板與右欄
（播放器＋結果）左右並排、右欄內播放器在結果清單上方；確認頁面本身不整頁捲動（每欄各自捲動，高度鏈
沒有壞掉）；700px 寬度下確認退回上下排列、無水平溢位；全程零 console error。截圖比對視覺符合預期。

### 8.2 YouTube 搜尋移到第一個頁籤，卡片加「播放」與「開始分析」（2026-08-26）

**需求**：使用者要求把「YouTube 搜尋」頁籤搬到主導覽最左邊的第一個位置，並在結果卡片上加兩顆按鈕
——「播放」與「開始分析」。

**修改**：

- **頁籤順序**：`TopNav.tsx`／`MobileBottomNav.tsx` 的 `NAV_ITEMS` 把 `/youtube` 移到陣列第一個。
  兩份清單本來就是各自維護（桌機用完整標籤「YouTube 搜尋」、手機版空間只有 64px 用縮寫
  「YouTube」），所以要改兩處。`App.tsx` 的落地頁跟著改成 `/youtube`——第一個頁籤同時是入口，
  否則開啟時停在第三個頁籤會不一致。
- **「播放」**：就地把卡片的縮圖區換成 YouTube 內嵌播放器（`youtube-nocookie.com/embed/<id>`，
  比 `www.youtube.com/embed` 少帶追蹤 cookie，行為相同），再按一次變「關閉播放」換回縮圖。刻意不
  開新分頁也不用 Modal——這頁的用途是「快速確認這支影片是不是要的」，離開頁面或被 Modal 蓋住都會
  打斷比較多支影片的流程。網址帶 `enablejsapi=1`，讓 8.3 的 keep-alive 能在切頁籤時 postMessage
  叫它暫停。
- **「開始分析」**（⚠️ **已被 8.4 取代**，這顆按鈕現在只下載、不分析；以下保留原始設計作為決策紀錄）：
  不是導去別的頁面，而是在卡片內直接跑完整條流程——`downloadYoutube(url)` 送出
  下載 job → `useJobPolling` 輪詢到完成 → 用回傳的 `job.video_id` 接 `analyzeVideo(video_id)` →
  再輪詢分析 job。等同使用者自己去「影片與分析」頁貼網址、下載完再勾選送分析，只是省掉換頁與複製
  網址。卡片內用一條進度條＋一行狀態文字（`準備下載…`／下載 job 的 `progress_message`／
  `排隊分析中…`／分析 job 的 `stage`／`✓ 分析完成`）顯示兩段 job 的進度，完成後 invalidate
  `['videos','pending']`／`['videos','library']`／`['stats']` 讓 Header 統計卡跟著更新。
  `DURATION_LIMIT_EXCEEDED` 比照 `VideosPage` 轉成中文訊息「影片長度超過分析上限」。
- **兩段 job 的接續用 ref 擋重複**：`downloadJob`／`analysisJob` 來自輪詢查詢，同一個終態會被讀到
  很多次，用 `handledDownload`／`handledAnalysis` 兩個 ref 記下已處理過的 job id，確保「接下一段」
  與「收尾（invalidate＋toast）」各只做一次。這跟 `VideosPage` 用「所有 job 都到終態」當收尾條件
  是不同寫法，因為卡片是一支影片對一組 job，不需要處理多選。
- **`README.md`／`YoutubeSearchPage` 的說明同步更新**：原本寫「只讀 metadata，不下載也不分析影片
  ——要下載分析請到『影片與分析』頁貼網址」已經不成立，改成「搜尋本身只讀 metadata，只有按下卡片
  的『開始分析』才會真的下載影片」。

**驗證**：`tsc -b`／`oxlint` 全過。Playwright 實跑：落地頁正確導到 `/youtube`；導覽列讀出
`['YouTube 搜尋','影片與分析','影片庫','搜尋結果','對話搜尋']`；實際搜尋「python 教學」拿到 12 筆
真實結果，12 張卡片各有一組「播放」「開始分析」；點「播放」確認 iframe `src` 正確、影片實際播放中；
展開詳情正常；全程零 console error。

**未驗證（誠實揭露）**：「開始分析」沒有實際點下去跑完一輪——它會真的下載影片並跑分析 pipeline、
消耗 OpenAI 費用，未經使用者同意不主動觸發。串接的是與「影片與分析」頁完全相同的 API 與輪詢邏輯，
但端到端沒有實跑過。（這條在 8.4 之後已無意義：那條分析鏈整段被移除了。）

### 8.3 頁籤切換不再清空狀態（keep-alive）（2026-08-26）

**問題**：使用者在 YouTube 搜尋頁打了關鍵字、拿到結果後切去別的頁籤，切回來整頁被清空。根因是
`App.tsx` 用 `<Routes>`／`<Route>`，同一時間只掛載當前路由，切頁籤等於整頁 unmount，所有
`useState` 全部歸零。這不是 YouTube 頁專屬問題，**五個頁籤都有**，其中「對話搜尋」最嚴重：
`ConversationPage` 在 mount effect 裡呼叫 `startConversation()`，所以每次切回去都會**重建一筆新的
conversation、聊天記錄整個清空**。這同時也是 `docs/09` §9、`docs/00` §3.5 記錄多時的「分析中途切換
頁籤，job 追蹤狀態會遺失」的同一個根因。

**修改**：改用 keep-alive——造訪過的頁籤留在 DOM 裡，只是隱藏起來，不再卸載。

- `App.tsx` 拿掉 `<Routes>`，改成一份 `PAGES` 清單（順序與 `TopNav` 一致）＋新的 `KeepAlivePage`
  包裝元件；未知路徑（含 `/`）用 `<Navigate to="/youtube" replace />` 導走。
- **隱藏方式用 `invisible absolute inset-0`（`visibility:hidden`）而不是 `hidden`
  （`display:none`）**：`display:none` 會讓元素失去 box，內部捲動容器的 `scrollTop` 被瀏覽器重設成
  0，切回來會跳回最上面；`visibility:hidden` 保留 box，捲動位置原封不動，而且一樣不會被鍵盤 focus
  到、也不會進無障礙樹，不需要另外加 `inert`／`aria-hidden`。`relative` 的定位基準刻意放在「沒有
  padding」的那一層 wrapper，這樣 `absolute inset-0` 的框跟作用中頁籤（in-flow 的 `h-full`）完全
  一樣寬高，切回來時排版與捲動位置才不會位移。
- **懶掛載**：只有造訪過的頁籤才進 `mountedPaths`，第一次點進去才付出初始化成本（避免一開 app 就
  替沒人要看的「對話搜尋」建一筆 conversation）。`mountedPaths` 用「render 期間呼叫自己的
  setState」這個 React 官方允許的寫法（有 `includes` 擋著不會無限迴圈），比放進 `useEffect` 少一次
  閃爍；一開始寫成 render 期間寫 ref，被 oxlint 的 `react(refs)` 規則點出來後改掉。
- **背景播放要主動暫停**：頁面看不見但還在 DOM 裡，不處理的話 YouTube 內嵌播放器與 `<video>` 會在
  背景繼續出聲。`KeepAlivePage` 在 active 由 true 轉 false 時呼叫 `pauseMediaIn()`：`<video>` 直接
  `pause()`；跨來源的 YouTube iframe 沒有 DOM API 可控，用 IFrame Player API 的 postMessage 指令
  （所以 8.2 的 embed 網址要帶 `enablejsapi=1`）。暫停不會丟掉播放位置，切回來按播放就接著看。

**連帶必須修的回歸（`SearchPage`）**：這頁原本只在 **mount 時**讀一次 `?q=`／`?video_id=`
（`useState` 初始值＋一個空依賴的 effect）。頁面不再卸載之後，從「影片庫」點第二次搜尋就完全沒反應
——這是 keep-alive 直接造成的回歸，不修不能上。改成每次 URL 參數變化都處理，消化完用
`setSearchParams({}, { replace: true })` 清掉參數，並用 `consumedParams` ref 記下剛處理過的字串，
避免 `setSearchParams` 自己造成的那次變化又被當成新請求；參數清空時把 ref 歸零，這樣連續帶同一組
關鍵字進來也會重新搜尋。同時把搜尋範圍改成隨參數一起傳進 `mutate`，不從 closure 讀
`scopeVideoId`——從影片庫按「只搜這支影片」進來時 `setScopeVideoId` 還沒生效，靠 closure 會搜成
全部影片（這是原本就潛伏、只是沒被觸發到的 bug）。

**驗證**：`tsc -b`／`oxlint` 全過。Playwright 實跑，在 YouTube 頁做出一組狀態後繞過「影片與分析／
對話搜尋／影片庫」再切回來，逐項比對：

| 項目 | 切走前 | 切回後 |
| --- | --- | --- |
| 關鍵字 | `python 教學` | `python 教學` |
| 結果卡片 | 12 張 | 12 張 |
| 展開中的卡片 | 1 張 | 1 張 |
| 內嵌播放器 | 1 個 | 1 個 |
| 捲動位置 | 320px | 320px |

另外確認：對話搜尋頁未送出的草稿（`打到一半切走的字`）切走再切回來還在；影片庫→搜尋結果**連續兩次**
都正確觸發搜尋（3.4 秒／1.5 秒，各找到 2 個片段），證明上面那個回歸確實修掉；390px 窄螢幕版面正常、
無橫向溢位、切回 YouTube 頁關鍵字仍在；全程零 console error。

**未驗證（誠實揭露）**：沒有實跑一輪真實分析來確認「分析中途切頁籤，進度顯示不再遺失」。就機制而言
根因（元件卸載）已經移除、輪詢在隱藏頁面持續進行，但端到端沒有實測過，`docs/09` §9 的那條限制先標記
為「應已解決、待實測確認」而不是直接劃掉。

**已知、刻意不處理**：手機版 `<main>` 是所有頁籤共用的捲動容器，**它的**捲動位置不是分頁籤記憶的
（桌機版頁面內部各自的捲動容器則有記憶）。要做的話得在 `KeepAlivePage` 額外存取 `<main>.scrollTop`，
這次先不做。

### 8.4 YouTube 卡片改成「加入待分析」，不在這頁跑分析（2026-08-26）

**需求**：使用者要求把 8.2 做的「開始分析」改成**只把影片加入「影片與分析」頁的待分析清單**，不要
在 YouTube 搜尋頁進行分析。

**為什麼原本的設計不對**：8.2 把「下載 → 分析」串成一顆按鈕，是為了省掉換頁與複製網址；但這讓一個
**用來瀏覽、挑片的頁面**變成可以直接花錢的地方——搜尋結果一次 12 張卡片，每張都有一顆按下去就開始
燒 OpenAI 預算的按鈕，誤觸成本很高，而且繞過了「影片與分析」頁「勾選後統一送出」這個原本就存在、
刻意做成需要確認的關卡。分析的觸發點應該只有一個。這頁的職責收斂成「挑片並收進來」。

**修改**（只動 `YoutubeResultCard.tsx` 與 `YoutubeSearchPage.tsx` 的說明文字）：

- 整段分析鏈移除：`analyzeVideo` import、`analysisJobId` state、`analyzeMutation`、輪詢分析 job 的
  第二個 `useEffect`、`handledAnalysis` ref 全部拿掉。現在只剩一段下載 job。
- 下載 job 完成後 invalidate `['videos','pending']` 與 `['stats']`（不再需要 `['videos','library']`
  ——影片是以 `pending` 狀態進 DB，不會出現在影片庫），狀態文字變成
  `✓ 已加入「影片與分析」待分析清單`，並跳一則 toast。
- **按鈕文字改成「加入待分析」、圖示 `Sparkles` → `ListPlus`**：留著「開始分析」但實際不分析會誤導
  使用者。終態文字是「已加入」（disabled），避免同一支影片被重複送下載。
- **錯誤特判換對象**：原本特判 `DURATION_LIMIT_EXCEEDED`，那是 analyze 端點才會丟的（`submit_download`
  只驗 `is_youtube_url` 與重複，長度上限在 `submit_analysis` 才檢查），改成特判 `DUPLICATE_JOB` →
  「這支影片已經在影片庫或下載中」。用搜尋結果挑片很容易挑到已下載過的，這是常態不是意外，不該把
  後端原始訊息直接丟給使用者。長度上限的把關仍在「影片與分析」頁按下分析時發生，行為不變。

**驗證**：`tsc -b`／`oxlint` 全過。Playwright 實跑，並用 `page.route()` 攔截
`POST /api/v1/videos/youtube` 與 `GET /api/v1/jobs/9001` 餵假的 job 進度——**這樣能走完整段 UI 流程
但不會真的下載影片、不動使用者的影片庫與資料庫**，同時攔下所有 POST 請求來證明沒有多打 API：

- 12 張卡片都是「加入待分析」，殘留的「開始分析」0 顆。
- 點下去 → 進度條＋`2.1MiB/s｜剩餘 00:12`（真實 job 的 `progress_message` 欄位）→
  `✓ 已加入「影片與分析」待分析清單`，按鈕變「已加入」且 disabled。
- **整輪只發出一個 POST：`/api/v1/videos/youtube`，沒有任何 `/analyze` 呼叫**——這是這次改動的核心
  驗收條件。
- 零 console error。

**未驗證（誠實揭露）**：沒有真的下載一支影片跑完 → 切到「影片與分析」頁確認它出現在待分析清單。
下載 API 與 job 輪詢是既有、已在「影片與分析」頁用了很久的路徑，卡片只是換一個地方呼叫它，但這段
端到端沒有實跑過（會在使用者的 `video/` 目錄留下檔案與一筆 DB 資料，未經同意不主動製造）。

### 8.5 移除「影片與分析」頁的新增影片區塊與本機上傳（2026-08-26）

**需求**：使用者要求把「影片與分析」頁上方的「新增影片」區塊整塊移除——YouTube 網址下載與本機上傳
都不要，影片一律由 8.4 的「YouTube 搜尋」頁卡片加入。

**這是 8.4 的自然收尾**：8.4 把「分析」收斂成只有一個觸發點，這一步把「加入影片」也收斂成只有一個
入口。兩頁的職責因此變成互不重疊——「YouTube 搜尋」負責挑片並收進來，「影片與分析」負責決定哪些
要送分析。

**修改**：

- `VideosPage.tsx` 刪掉整個第一張 `Card`，連同 `sourceMode`／`url`／`downloadJobId`／`downloadError`／
  `uploadPercent`／`uploadError` 六個 state、`downloadMutation`、下載 job 的 `useJobPolling` 與收尾
  `useEffect`、`onDownloadSubmit`／`onFileSelected`，以及 `SOURCE_OPTIONS` 常數。頁面剩下待分析清單
  這一張 Card（`flex min-h-0 flex-1 flex-col` 讓它自己撐滿高度，版面不需要另外調）。
- **空狀態必須補一個出口**：原本的提示是「可貼上 YouTube 網址或選擇本機影片」，新增區塊沒了之後這句
  會變成無路可走的死路。改成「到『YouTube 搜尋』頁找影片，按卡片上的『加入待分析』就會出現在這裡」，
  並加一顆 `<Link to="/youtube">` 的行動按鈕。為此 `EmptyState` 新增一個選填的 `action?: ReactNode`
  ——這是這次唯一擴充的共用元件 API，用在「這個空狀態要靠別的頁面才能解掉」的情境。
- **刪除變成孤兒的檔案（使用者明確同意後才刪，依 CLAUDE.md 規則）**：`components/SegmentedControl.tsx`
  （只有來源切換在用）、`components/Dropzone.tsx`（只有本機上傳在用），以及 `api/client.ts` 的
  `uploadVideo()`（XHR + `onProgress` 上傳進度，是 Phase 2 唯一用到 XMLHttpRequest 而非 fetch 的地方）。
  同時刪掉先前幾輪留在 `frontend/` 的三支 Playwright 驗證腳本 `_shot*.mjs`（本來就沒進版控）。
  **後端 `POST /videos/upload` 與它的測試都保留沒動**：這次只拆前端入口，後端能力留著，之後要恢復
  本機上傳是加回一個前端函式的事。Phase 2（§5）記錄的 `Dropzone`／`SegmentedControl` 設計不回頭改，
  以這一節為準。

**能力損失（誠實揭露，使用者已知情）**：移除之後**沒有任何地方能貼一條指定的 YouTube 網址**——
「YouTube 搜尋」頁只吃關鍵字，手上有明確網址時得先想個關鍵字把它搜出來。本機上傳則是使用者明確
表示不需要。若之後要恢復「貼網址」這條路，建議做在 YouTube 搜尋頁的搜尋框上（偵測輸入是網址就直接
跑下載），而不是把區塊加回「影片與分析」頁，這樣入口仍然只有一個。

**驗證**：`tsc -b`／`oxlint`／`build` 全過（bundle 從 357.95 kB 降到 353.58 kB）。Playwright 實跑
`/videos`：「新增影片」標題、YouTube 網址輸入框、「下載影片」按鈕、來源切換（`role=radio`）、
Dropzone 的 `input[type=file]` 五項全部確認為 0 個；頁面剩 1 張 Card；待分析清單正常顯示 3 支真實
影片；勾選前「開始分析」為 disabled、勾選後啟用（確認核心流程沒被拆壞）；390px 無橫向溢位；零
console error。空狀態另外用 `page.route()` 把 `GET /videos?status=pending` 假裝成 `[]` 驗過（不刪
任何真實資料）：標題、提示、「去 YouTube 搜尋」按鈕都正確，點下去確實導到 `/youtube`。

### 8.6 移除影片庫的搜尋列，「搜尋結果」頁籤改名「搜尋影片」（2026-08-26）

**需求**：使用者要求移除「影片庫」頁上方那條自由文字搜尋列，搜尋只在原本的「搜尋結果」頁籤進行，
並把該頁籤改名為「搜尋影片」。

**跟 8.4／8.5 是同一條線**：8.4 讓分析只有一個觸發點，8.5 讓加入影片只有一個入口，這一步讓**自由
文字搜尋也只有一個入口**。影片庫那條搜尋列本來就只是「把字帶去 `/search?q=…` 然後自己跳頁」的捷徑，
留著等於同一件事有兩個看起來不一樣的起點。頁籤改名順帶修掉一個名實不符：「搜尋結果」描述的是輸出，
但那頁本來就是**執行**搜尋的地方。

**修改**：

- `LibraryPage.tsx` 刪掉頁面最上方那張 `Card`（`SearchField` ＋送出按鈕）、`query` state、
  `onSearchSubmit`，以及 `SearchField` 的 import。`useNavigate` 保留——「在此影片內搜尋」還要用。
- **「在此影片內搜尋」刻意保留不動**：它帶的是 `?video_id=`（設定搜尋範圍），不是查詢字串，點下去
  是跳到「搜尋影片」頁再打字，符合「只在搜尋影片頁進行搜尋」。
- `TopNav.tsx`／`MobileBottomNav.tsx` 的 `/search` 標籤改成「搜尋影片」。**路由本身維持 `/search`
  不變**——改路由會讓既有書籤失效，而且 `?video_id=` 那條跳轉、`docs/09`／`docs/11` 裡一堆
  `/search` 引用都得跟著改，純粹是換顯示文字就不值得付這個代價。
- `SearchPage.tsx` 的檔頭註解補上新頁籤名與「全站只有這一頁能輸入自由文字搜尋」的說明。

**刻意不做**：`SearchPage` 處理 `?q=` 的分支留著。app 內已經沒有任何地方會帶 `q` 過來（8.6 之後只剩
`?video_id=`），但手動輸入或書籤網址仍然有效，刪掉只是多餘的破壞；那段邏輯本身也是 8.3 keep-alive
回歸修正的一部分，動它要重新驗證一次不划算。

**驗證**：`tsc -b`／`oxlint` 全過。Playwright 實跑：導覽列讀出
`['YouTube 搜尋','影片與分析','影片庫','搜尋影片','對話搜尋']`，390px 底部導覽同步改名；影片庫頁
`main` 內可見的 `input` 與名為「搜尋」的按鈕都是 0 個、剩 2 張 Card（清單＋詳細面板）；點選影片後
「在此影片內搜尋」仍在，按下去正確跳到 `/search` 並顯示「目前作用中的篩選：只在《不用竹簾捲壽司…》
中搜尋」；「搜尋影片」頁自己的輸入框仍在（全站唯一一個）；390px 無橫向溢位；零 console error。

### 8.7 影片庫：預設選第一支影片、移除兩個模態篩選（2026-08-26）

**需求**：點進「影片庫」頁時右側詳細面板不要是空白，預設帶出第一支影片；另外把「無字幕」與
「純畫面」兩個篩選按鈕與功能移除。

**修改**：

- **預設選取刻意用「推導」而不是 `useEffect` 同步 state**：
  `const selected = rows.find((v) => v.id === selectedId) ?? rows[0] ?? null`。這樣切換篩選／排序後
  如果原本選的那支不在清單裡了，會自動落回第一筆，不需要額外的 effect，也不會出現「面板空白一瞬間」
  再補上的閃爍。
- **清單反白改成比對 `selected?.id` 而不是 `selectedId`**：預設選中的第一筆還沒被點過，`selectedId`
  仍是 `null`，用它會變成「右側有內容、左側沒有任何一列反白」的錯位。這是這個改法唯一的陷阱。
- 篩選只留 `all`／`analyzed`／`failed`，`FilterKind` 型別與 `useMemo` 裡的兩段條件一併刪掉。
- 順手修掉兩句已經不成立的文案：空清單提示「先在『影片與分析』頁籤下載並分析影片」（8.5 之後那頁
  已經不能下載）改成「先到『YouTube 搜尋』頁加入影片，再到『影片與分析』頁分析」；右側「尚未選取
  影片」改成「沒有可顯示的影片」——有了預設選取之後，「尚未選取」已經不可能是真的。

**驗證**：`tsc -b`／`oxlint` 全過。Playwright 走「從別的頁籤點進影片庫」的真實路徑：篩選按鈕只剩
`['全部','分析完成','分析失敗']`、「無字幕」「純畫面」各 0 個；右側沒有空白狀態，清單第一列標題與右側
面板標題一致、第一列有反白（`rgb(247, 228, 220)`）；切換篩選後自動落回第一筆不會變空白；手動點第三列
面板正常跟著換；390px 無橫向溢位；零 console error。

### 8.8 影片庫右側面板改成不捲動的固定版面（2026-08-26）

**需求**：左右框各佔一半；右方不要捲動；摘要移到三個按鈕下方（最下方），因為摘要長度不固定；
縮圖放到最適大小。中間經過幾輪來回調整，這裡記最終狀態與過程中的取捨。

**先量再改**：改之前先用 Playwright 量出「到底有沒有超出、超出多少」——1440×900 剛好放得下，但
**1366×768（文件 10 指定的目標視窗）有 3 支影片溢出 19～43px**。有了這個數字才知道要爭取多少空間，
不是憑感覺縮東西。

**最終版面**（`VideoDetailPanel`）：

1. 面板本身是 `md:h-full` 的 flex column，外層 `Card` 用 `md:overflow-hidden`（不是 `overflow-auto`）。
2. 縮圖／標題＋meta／按鈕／job 狀態全部 `shrink-0`。
3. **摘要放最後**並吃掉剩下的高度（`md:min-h-0 md:flex-1 md:overflow-auto`）——它是整個面板唯一會捲
   的地方，卡片本身永遠不捲。摘要放最下面的理由跟使用者說的一樣：長度不固定，擺在中間會把按鈕推到
   不固定的位置，換一支影片按鈕就跳一次。文案裡的「按下方『重新產生摘要』」跟著改成「按上方」。
4. 縮圖 `VideoPoster` 新增 `size="fill"`（`aspect-video w-full`），並在詳細面板加 `md:max-h-[42vh]`
   ——寬度吃滿、比例由 `aspect-video` 決定、高度在矮螢幕由 `max-h` 壓回來、`object-cover` 負責裁切。
   高度跟著視窗長，所以摘要下方不會留一片空白。≤900px 不套 `max-h`（手機本來就整頁捲動）。

**中間試過但退掉的做法（保留下來免得之後又繞一次）**：一度把縮圖與標題／meta／標籤改成**並排**，
省下約 230px 確實解決了溢出，但縮圖被壓到只剩 256px 寬（1366 下），使用者回報「縮得太小」。改回
滿版寬度＋`max-h` 之後，1366 下縮圖是 609×323，比並排版大得多，而且一樣不溢出——所以**限制高度比
限制寬度好**：寬度是視覺主體，高度才是真正稀缺的資源。

**三個標籤移除**：使用者要求把「有字幕／有畫面描述／有 OCR」整列拿掉，`Badge` 在這頁因此沒有其他
用途，import 一併移除（元件檔本身保留，其他頁面還在用）。這也讓縮圖的 `max-h` 從 34vh 放寬到 42vh。

**驗證**：`tsc -b`／`oxlint` 全過。Playwright 對 10 支影片 × 4 種視窗逐一量測卡片的
`scrollHeight - clientHeight`：

| 視窗 | 卡片溢出 | 底部剩餘空白 | 縮圖 |
| --- | --- | --- | --- |
| 1920×1080 | 0px | 32px | 696×392 |
| 1440×900 | 0px | 32px | 646×363 |
| 1366×768 | 0px | 32px | 609×323 |
| 1180×700 | 0px | 32px | 516×290 |

40 種組合全部 0px 溢出，連摘要的內部捲動都是 0px；剩下的 32px 就是 `Card` 自己的 `p-4` 內距，等於
沒有多餘空白。標籤殘留 0 個。390px 無橫向溢位、零 console error。

### 8.9 搜尋影片：搜完自動選第一名、預設不自動播放（2026-08-26）

**需求**：搜尋完成後右方自動帶入第一個片段，除非沒有搜到任何片段才顯示其他提示；預設只顯示、
不要自動播放。

**修改**：

- `onSuccess` 從 `setSelectedIndex(null)` 改成 `setSelectedIndex(resp.results.length > 0 ? 0 : null)`。
- **右側空狀態拆成兩種**：有結果就一定有選取，所以「尚未選取片段」已經不可能是真的。改成用
  `searchMutation.isSuccess` 區分「還沒搜過」（`搜尋後這裡會顯示片段與播放器`）與「搜過但沒找到」
  （`沒有找到相關片段` ＋三條調整建議）。
- **`VideoPlayer` 新增 `autoPlay` prop（預設 `true`）**：使用者主動點某個片段時是 true（點了就想看），
  程式自己帶出來的預設選取傳 false，只 seek 到該時間點、不播。`SearchPage` 用一個 `playOnSelect`
  state 區分這兩種來源。`autoPlay` 有放進 seek `useEffect` 的 deps——使用者點的是「已經選中的那一筆」
  時 `videoId`／`startSec` 都沒變，只有 `autoPlay` 從 false 翻成 true，沒有它那次點擊不會播。
  **對話搜尋頁沒傳這個 prop，行為維持原樣。**

**驗證**：`tsc -b`／`oxlint` 全過。Playwright 用真實搜尋：查「動物」→ 8 個片段、右側自動載入
`/api/v1/videos/2/stream`、**停在暫停狀態，1.5 秒後時間仍沒前進**（確認不是「播了一下才停」）；
點第三筆結果 → 立刻開始播放（439.1s），使用者主動點擊的行為不變。另外確認「不播」不等於「沒 seek」：

| 查詢 | 第一名時間 | 播放器 `currentTime` | 結果 |
| --- | --- | --- | --- |
| 棒球 | 00:09–00:19 | 9.5s | ✓ seek 正確、暫停 |
| 工廠 | 05:54–06:04 | 353.8s | ✓ seek 正確、暫停 |

「沒有搜到」的分支用 `page.route()` 讓 `/api/v1/search` 回 0 筆驗過（不打真的 API、零花費）：右側正確
顯示提示且不會出現空的播放器。真實查詢幾乎搜不出 0 筆——語意搜尋總會找到些什麼——所以這條路徑只能
用 mock 測。

### 8.10 三頁主從版面統一成左右各半（2026-08-26）

**需求**：影片庫／搜尋影片／對話搜尋的左右框比例調成一致，切換頁籤時 UI 風格統一。

**修改**：搜尋影片與對話搜尋原本是 `md:w-3/5`／`md:w-2/5`（60/40），改成跟影片庫一樣的
`md:w-1/2`。三處都加了同一句註解「改比例要三頁一起改」。

**踩到的坑（值得記）**：改成 `md:w-1/2` 之後第一次量測，影片庫仍然是 **746/730**，跟另外兩頁差 8px。
原因是 flex item 的 `min-width: auto`——影片庫**右**欄有 8.8 加上的 `md:overflow-hidden`，依規範
`overflow` 非 `visible` 會讓 `min-width:auto` 解析成 0，所以右欄可以被壓縮到 50% 以下；但**左**欄沒有
overflow，撐不下最小內容寬度（清單標題），就多佔了 8px。`w-1/2` 寫得再對也沒用。修法是給六個欄位
全部補上 `min-w-0`，讓 50% 是真的 50%，順帶讓三頁的欄位 class 結構一致，之後不會再因為某一頁多加了
overflow 就悄悄跑掉。

**驗證**：`tsc -b`／`oxlint` 全過。Playwright 逐頁量 bounding box：

| 視窗 | 影片庫 | 搜尋影片 | 對話搜尋 | 右欄起點 |
| --- | --- | --- | --- | --- |
| 1920×1080 | 738 / 738 | 738 / 738 | 738 / 738 | x=968 三頁一致 |
| 1440×900 | 688 / 688 | 688 / 688 | 688 / 688 | x=728 三頁一致 |
| 1366×768 | 651 / 651 | 651 / 651 | 651 / 651 | x=691 三頁一致 |

零 console error。

**仍然存在、刻意不處理的差異**：搜尋影片頁上方多一張搜尋列 `Card`，所以它的雙欄比另外兩頁低約
130px 起跳——那是這頁的功能需求，拿不掉。右欄捲動行為也還不一致（影片庫是 8.8 的「卡片不捲、只有
摘要內部捲」，另外兩頁仍是整張卡片捲），要統一是版面重構不是改個 class，這次沒做。

### 8.11 分析長度上限 20 分鐘 → 1 小時（2026-08-26）

**需求**：使用者要求把影片長度限制改成 1 小時。

**修改**：`pipeline/analyzer.py` 的 `MAX_DURATION_SEC` 由 `20 * 60` 改為 `60 * 60`。這是這次唯一
一處後端改動。既有測試用符號引用這個常數（`tests/api/test_api_videos.py:49` 用
`analyzer.MAX_DURATION_SEC + 1`、`tests/test_services_video.py:80` 用 `// 60`），所以不需要改測試。

**兩點要記清楚**：

1. **這道限制擋的是「分析」不是「下載」**。`job_manager.submit_download()` 只驗 `is_youtube_url` 與
   重複（`find_existing_by_url`／`has_active_download_job`），完全沒有長度檢查——所以 8.4 的
   「加入待分析」任何長度的影片都收得進來，是按下「開始分析」時才會被 422 擋。
2. **`BUDGET_USD = 0.30` 沒有跟著調，很可能會先撞到它**。實測 4～7 支影片（最長約 18 分鐘）花費
   $0.0965～$0.1885，往 60 分鐘外推大概率超過 $0.30。預算是「跑到哪累加到哪、超過就 break」，所以
   長影片會變成**部分完成**——分析到一半停下，前面的片段仍可搜尋，後半段沒有索引。要不要一起調高
   `BUDGET_USD` 交給使用者決定，這次沒有自行更動。同樣的說明也寫在 `analyzer.py` 的註解裡。
   **後續**：已於 §8.12 調到 $0.80。

**驗證**：後端全套測試 **267 passed**（1 deselected）。

### 8.12 分析預算上限 $0.30 → $0.80（2026-08-26）

**需求**：§8.11 把長度上限放寬到 1 小時時，`BUDGET_USD` 刻意留在 $0.30 沒動（要不要調交給使用者
決定）。實際情況是 60 分鐘影片幾乎一定會撞到 $0.30 而變成部分完成，所以這次把它一起調上去。

**修改**：`pipeline/analyzer.py` 的 `BUDGET_USD` 由 `0.30` 改為 `0.80`，並把推導寫進常數旁的註解。
這是這次唯一一處程式碼改動。測試不需要改——兩個會碰到預算的測試都自己 `monkeypatch` 成 0.20
（`tests/test_analyzer.py:128`、`:457`，註解明講「不依賴正式常數的實際值」），
`tests/test_analyzer_integration.py:80` 是 `< analyzer.BUDGET_USD` 的符號比較。

**$0.80 怎麼來的**（用 `app.db` 裡 10 支已分析影片反推，範圍 1.0～18.6 分鐘）：

```
成本 ≈ ASR($0.006/分，asr.PRICE_PER_MINUTE_USD 固定值)
       + 每片段 $0.00050~$0.00090（VLM＋embedding＋摘要）
```

| 項目 | 實測值 |
|---|---|
| 每片段費率 | $0.00050～$0.00091（10 支中 9 支落在 $0.00050～$0.00054，$0.00091 是唯一離群的 `video_id=1`） |
| 片段密度 | 5.0～6.2 個/分 |
| 單支總費用 | $0.0098（1.0 分）～$0.1711（18.6 分） |

往 60 分鐘外推：

| 情境 | 算式 | 結果 |
|---|---|---|
| 實測密度、典型費率 | `60×0.006 + 360×0.00053` | ~**$0.55** |
| 實測密度、最壞觀測費率 | `60×0.006 + 360×0.00091` | ~**$0.70** |
| **結構上限密度、最壞觀測費率** | `60×0.006 + 450×0.0009` | **$0.765** |

密度不會失控是這個推導能成立的關鍵：`scene_detect` 會把場景正規化到 8～12 秒
（`MERGE_BELOW_SEC`／`SPLIT_ABOVE_SEC`），所以密度的**結構上限**是 `60/8 = 7.5` 個/分，
快剪內容也一樣。最壞情況 $0.765 仍在 $0.80 內，但**餘裕只有 4.6%**。

**三點要記清楚**：

1. **$0.80 不是 60 分鐘影片真正的瓶頸，ASR 才是**。`asr._extract_audio()` 固定輸出 64kbps 單聲道
   mp3（實測 7,998 bytes/s），Whisper 的 25MB 上傳上限換算後約 **52～55 分鐘**；而且 ASR 例外會讓
   **整支分析失敗**（不是略過字幕繼續跑）。所以超過約 52 分鐘的影片會先卡在 ASR，根本走不到預算
   判斷，也走不到 `MAX_DURATION_SEC` 的 60 分鐘。這個缺口沒有實測驗證過，是從位元率與上限反推的。
2. **`BUDGET_USD` 是「每支影片」各自算的，批次分析沒有任何總量上限**。目前的上限全貌：

   | 項目 | 值 | 位置 |
   |---|---|---|
   | 一次可勾選送出分析的影片數 | **無上限** | `pages/VideosPage.tsx` `onAnalyzeClicked()` 逐一 POST，沒有筆數檢查 |
   | 同時實際執行的分析 | **1 支** | `services/job_manager.py` process 級旗標＋鎖序列化，其餘留在 `queued` |
   | 單支影片長度 | **60 分鐘** | `analyzer.MAX_DURATION_SEC`（見 §8.11） |
   | 單支影片費用 | **US$0.80** | `analyzer.BUDGET_USD`（本節） |
   | 單支影片內 VLM 併發 | **3** | `analyzer.VLM_BATCH_SIZE` |
   | 下載工作併發 | **無上限** | 不呼叫 OpenAI，不序列化 |

   所以一次勾 10 支的批次，理論最高就是 10×$0.80，中間沒有任何機制會攔下來或警示。
3. **撞到兩道上限的行為不一樣**：超過長度在建立 job 時就被擋（`DURATION_LIMIT_EXCEEDED`，422），
   批次裡其他影片照常送出；超過預算則是**跑到哪算到哪的提前截斷**，影片仍會變成已分析，只在
   stage note 標「已達預算上限（US$0.80），完成 N/M 片段」——前面的片段可以搜尋，後半段沒有索引。

**驗證**：後端全套測試 **266 passed**（1 deselected）。比 §8.11 記的 267 少一題，是因為 §8.13 移除了
`test_search_export_returns_csv`，跟這次改動無關。60 分鐘影片的實際費用**還沒有實測過**——上表全部
是外推值，第一支真正的長影片跑完之後應該回來對一次。

### 8.13 搜尋影片頁精簡：拿掉 CSV 匯出與融合分數說明，模態分數改百分比條（2026-08-26）

**需求**（三件小事一起做）：

1. 空狀態的 icon 置中。
2. Evidence Panel 拿掉「主要命中來源」與「融合分數 0.236（排序依據）・RRF 融合（…）」兩行。
3. 搜尋影片頁拿掉「匯出 CSV」；字幕／畫面／OCR 三個分數改用跟「最終相似度」一樣的百分比條，並排一列。

**修改**：

- `components/EmptyState.tsx`：icon 外層由 `mx-auto` 改成 `flex justify-center`。**原因**：那層
  `<div>` 是 block 且沒設寬度，會撐滿容器，`mx-auto` 等於沒作用；而 Tailwind preflight 把 `svg` 設成
  `display: block`，父層的 `text-center` 也管不到它，icon 就貼在最左邊。
- `components/EvidencePanel.tsx`：刪掉 `hit_source`／`fusion_score`／`fusion_strategy` 三個欄位的顯示；
  `ScoreCell` 改吃原始分數並改用 `SimilarityBar`，外層 `grid-cols-3` 三欄同列。
- `components/SimilarityBar.tsx`：`ratio` 改收 `number | null`，null（該模態沒內容，例如整段無字幕）
  顯示空條＋灰字 N/A；百分比文字加 `shrink-0`，欄位窄時先縮色條、不擠壓數字。
- `pages/SearchPage.tsx`／`api/client.ts`／`lib/format.ts`：移除「匯出 CSV」按鈕、`exportSearchCsv()`
  與跟著沒人用的 `formatScore()`。
- `api/search.py`：移除 `POST /api/v1/search/export` 與 `_format_time_range()`，`csv`／`io`／
  `StreamingResponse` 三個 import 一併清掉。`tests/api/test_api_search.py` 移除
  `test_search_export_returns_csv`。

**兩點要記清楚**：

1. **三模態分數用百分比條在語意上是對的**：`similarity` 就是 transcript／visual／OCR 三個 cosine
   分數取最高（`pipeline/search.py:232`），四條共用同一個尺度，最高的那條必定等於上方「最終相似度」。
   跟它同框的 `fusion_score` **不是**同一個尺度（RRF 融合值，排序依據），所以它被拿掉之後不要再用
   同一種條狀圖把它加回來。
2. **`docs/08` §API 清單仍列著 `POST /api/v1/search/export`**，那是遷移期的設計文件、保留為歷史紀錄，
   以本節為準。Tkinter 版的 CSV 匯出（`docs/07` §5）不受影響，這次只動 Web。

**驗證**：後端全套測試 **266 passed**（1 deselected；比 8.11 少的一支就是刪掉的 CSV 測試）。前端
`tsc --noEmit`／`oxlint` 全過。
