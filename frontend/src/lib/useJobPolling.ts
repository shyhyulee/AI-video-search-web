import { useQueries, useQuery } from '@tanstack/react-query'
import { getJob } from '../api/client'
import type { Job } from '../api/types'
import { isTerminal } from './jobStatus'
import { jobKey } from './queryKeys'

function stopWhenTerminal(status: Job['status'] | undefined): number | false {
  return isTerminal(status) ? false : 1000
}

/** 輪詢單一 job 直到終態（completed／failed），對齊 Tkinter 版
 * `self.after(150, poll_fn)` 的 Queue 輪詢模式，見
 * docs/archive/09-web-ui-migration-plan.md「Category A / B」。1 秒一次，比桌面版
 * 150ms 稀疏——HTTP 輪詢不需要那麼即時，多數階段本來就只有預估進度。 */
export function useJobPolling(jobId: number | null) {
  return useQuery<Job>({
    queryKey: jobKey(jobId),
    queryFn: () => getJob(jobId as number),
    enabled: jobId !== null,
    refetchInterval: (query) => stopWhenTerminal(query.state.data?.status),
  })
}

/** 同時輪詢多個 job（例如多選影片一起送出分析，Job Manager 序列化後只有
 * 一個 running、其餘 queued，各自都要能顯示狀態），見
 * docs/archive/09-web-ui-migration-plan.md 3.2 節。 */
export function useJobsPolling(jobIds: number[]) {
  return useQueries({
    queries: jobIds.map((id) => ({
      queryKey: jobKey(id),
      queryFn: () => getJob(id),
      refetchInterval: (query: { state: { data?: Job } }) => stopWhenTerminal(query.state.data?.status),
    })),
  })
}
