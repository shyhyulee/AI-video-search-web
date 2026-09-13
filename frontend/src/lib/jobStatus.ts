import type { Job } from '../api/types'

/** 背景工作狀態的兩個共用判斷。
 *
 * 只抽這兩個，不把所有 `status === '...'` 都收進來：其餘的比較是**顯示分支**
 * （completed 顯示「✓ 分析完成」、failed 顯示錯誤訊息與重試鈕、queued 顯示
 * 「排隊中」），它們要分辨的正是這兩個函式刻意抹平的差別，收進來只會讓呼叫端
 * 再拆一次。
 *
 * 兩者不是互補的：`analyzing` 這種衍生狀態在有些地方是
 * `video.status === 'analyzing' || isActive(job?.status)`，也就是影片本身的狀態
 * 也算數——重新整理之後 job 還沒接回來的那幾秒，只有影片的 status 說得準。
 */

type Status = Job['status'] | undefined

/** 已經到終態（成功或失敗），不會再變了。輪詢該停、收尾該做一次。 */
export function isTerminal(status: Status): boolean {
  return status === 'completed' || status === 'failed'
}

/** 還在進行中（排隊中或執行中）。用來決定按鈕要不要停用、清單要不要繼續輪詢。 */
export function isActive(status: Status): boolean {
  return status === 'queued' || status === 'running'
}
