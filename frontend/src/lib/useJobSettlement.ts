import { useEffect, useRef } from 'react'
import type { Job } from '../api/types'
import { isTerminal } from './jobStatus'

/** 「每個背景工作到終態時，收尾剛好做一次」。
 *
 * 原本有三份各自的實作：LibraryPage 的 `settledJobIds`、VideosPage 的
 * `notifiedJobIds`、YoutubeResultCard 的 `handledDownload`。三處在做同一件事，
 * 但一個用 Set、一個用單一 id、去重的寫法也各不相同。
 *
 * **去重不是效能微調**：job 輪詢會把同一個終態讀到很多次，而 effect 每次重跑
 * 都會再收尾一輪——對後端連發 invalidate、對使用者疊出好幾則一模一樣的通知。
 *
 * `onSettled` 收的是「這一輪**新**到終態的工作」而不是單一 job：VideosPage
 * 會同時追蹤多個分析工作，要能逐一跳通知、但清單與統計只刷一次。
 *
 * 刻意不給 deps array，讓它每次 render 後都跑一遍：呼叫端傳進來的 `jobs`
 * 幾乎都是當場算出來的陣列（`[job]`、`.map()`），identity 本來就每次都不同，
 * 給 deps 只是看起來嚴謹。真正保證「只做一次」的是下面那個 ref，不是 deps。
 */
export function useJobSettlement(
  jobs: (Job | undefined)[],
  onSettled: (settled: Job[]) => void,
): void {
  const handledIds = useRef<Set<number>>(new Set())

  useEffect(() => {
    const settled = jobs.filter(
      (job): job is Job =>
        job !== undefined && isTerminal(job.status) && !handledIds.current.has(job.id),
    )
    if (settled.length === 0) return
    // 先全部記起來再呼叫 onSettled。**這個順序目前沒有可觀察差異**——調換過來
    // 跑完整組 e2e 仍然全綠，因為 effect 裡的 setState 要等 effect 執行完才
    // 重繪，那時候記錄早就寫好了。留這個順序不是在修 bug，是讓「已收尾的 job
    // 不會再收尾一次」這個不變式跟 callback 做了什麼無關。
    for (const job of settled) handledIds.current.add(job.id)
    onSettled(settled)
  })
}
