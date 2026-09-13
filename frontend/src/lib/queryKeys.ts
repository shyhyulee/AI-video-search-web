/** 全站 react-query 的 query key，集中在這裡。
 *
 * 為什麼非集中不可：key 決定「誰跟誰共用同一份快取」與「invalidate 打得到誰」。
 * 原本 22 處字面值散在 8 個檔案，任何一處打錯都**不會報錯也不會壞畫面**——
 * react-query 換一個 key 照樣呼叫同一個 queryFn，清單照樣載入，只是那個元件
 * 自己拿一份快取、invalidate 也打不到它。實測過：把 LibraryPage 的 key 改成
 * `['videos','libraryX']`，19 支 e2e smoke 有 18 支照樣綠燈。
 *
 * 所以除了集中，還有一條靜態檢查（`scripts/check-query-keys.mjs`，掛在
 * `npm run lint` 上）：query key 的字面值只准出現在這個檔案裡。少了那條，
 * 這個檔案就只是「建議」而不是「唯一來源」。
 *
 * 全部回傳 `as const` 的 tuple：react-query 用結構相等比對 key，`as const`
 * 讓 TypeScript 記住每個位置的字面值型別，打錯字在編譯期就看得到。
 */

/** Header 的統計卡（GET /stats）。分析、刪除、整理文件之後都要 invalidate 它。 */
export const statsKey = () => ['stats'] as const

/** 「影片庫」頁的清單（GET /videos）。
 *
 * `SearchScopeBar` 與 `ConversationPage` 也用同一個 key——它們只是要把範圍裡的
 * video id 換成標題，共用快取就不必多打一次 API。這正是 key 打錯時會安靜壞掉
 * 的地方：改壞了不會有人發現，只會多幾個請求。 */
export const libraryVideosKey = () => ['videos', 'library'] as const

/** 「影片與分析」頁的待分析清單（GET /videos?status=pending）。 */
export const pendingVideosKey = () => ['videos', 'pending'] as const

/** 還沒到終態的工作（GET /jobs?active=true）。
 *
 * 「影片庫」與「影片與分析」兩頁都用 `'analysis'` 這個型別，共用同一份快取與
 * 同一組請求——兩頁可能同時開著（頁籤是 keep-alive 的）。 */
export const activeJobsKey = (jobType: 'analysis' | 'download') =>
  ['jobs', 'active', jobType] as const

/** 單一工作的輪詢（GET /jobs/{id}）。 */
export const jobKey = (jobId: number | null) => ['job', jobId] as const

/** 一支影片整理好的文件（GET /videos/{id}/document）。 */
export const videoDocumentKey = (videoId: number) => ['video-document', videoId] as const

/** YouTube 搜尋結果（GET /youtube/search）。查詢字串是 key 的一部分，
 * 換關鍵字就是另一份快取。 */
export const youtubeSearchKey = (query: string) => ['youtube-search', query] as const
