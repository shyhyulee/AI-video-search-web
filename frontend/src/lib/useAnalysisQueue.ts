import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listActiveJobs, listVideos } from '../api/client'
import type { Job } from '../api/types'
import { isActive } from './jobStatus'
import { activeJobsKey, pendingVideosKey } from './queryKeys'
import { useJobsPolling } from './useJobPolling'
import { useJobSettlement } from './useJobSettlement'

/** 「影片與分析」頁的資料層：待分析清單、以及跑在它上面的分析工作。
 *
 * 看板上這張卡片原本叫 `useAnalysisJobs`，只打算搬走 job 追蹤。實際動手才發現
 * **清單與工作的輪詢節奏互為輸入**，切在中間會變成循環依賴：
 *
 *   - 清單要不要每 3 秒重取，看「有沒有工作在跑」（`anyActive`，來自 job 輪詢）
 *   - 工作探索要不要加密，看「清單裡有沒有 analyzing 的影片卻還沒追蹤到」
 *
 * 所以兩者一起搬。頁面元件因此不再碰 react-query，只讀這個 hook 回傳的東西。
 */

/** 有工作跑完（成功或失敗）時回報的一筆。
 *
 * 帶 `title` 是因為那一刻影片可能已經不在清單上了：分析完成的影片會馬上移去
 * 影片庫，從待分析清單重取的結果裡就查不到標題。所以 hook 自己留一份標題快照。 */
export interface SettledAnalysis {
  job: Job
  title: string
}

/** 有分析在跑時，清單本身也要跟著重取，不能只靠 job 輪詢。
 *
 * 兩件事只有清單知道：影片的 `status` 什麼時候從 analyzing 變成 analyzed
 * （＝該離開這一頁了），以及 `pipeline_stage` 目前跑到哪。job 輪詢只看得到
 * job 表。3 秒是折衷：比 job 輪詢（1 秒）稀疏，因為清單查詢還要多做一次
 * modality flags 的聚合。 */
const LIST_POLL_MS = 3000

/** 沒有任何分析在跑時，仍然定期問一次「有沒有進行中的分析」。
 *
 * 這是重新整理後能接回進度的關鍵：追蹤清單只活在 React state，F5 之後是空的，
 * 得靠這支查詢從後端把 job 撈回來。8 秒足夠——它只負責「發現」，發現之後
 * 每秒的進度更新由 useJobsPolling 接手。 */
const ACTIVE_JOBS_DISCOVERY_MS = 8000

export function useAnalysisQueue(onSettled: (finished: SettledAnalysis[]) => void) {
  // 追蹤中的分析 job：video_id -> job_id。兩個來源——呼叫端送出分析時給的
  // `track()`，以及下面 activeJobs 從後端撈回來的進行中工作（重新整理後靠它
  // 接回來）。已完成的 job 不從這裡移除：useJobsPolling 對終態 job 會停止
  // 輪詢，留著不花成本，而且要留著呼叫端才顯示得出「✓ 分析完成」與重試。
  const [analysisJobs, setAnalysisJobs] = useState<Record<number, number>>({})

  const trackedJobIds = useMemo(() => Object.values(analysisJobs), [analysisJobs])
  const jobQueries = useJobsPolling(trackedJobIds)
  const anyActive = jobQueries.some((query) => isActive(query.data?.status))

  // `Object.keys` 跟上面 `Object.values` 走同一個物件、列舉順序相同，所以第 i
  // 個 key 對應第 i 個查詢。
  const jobByVideoId = useMemo(() => {
    const map = new Map<number, Job | undefined>()
    Object.keys(analysisJobs).forEach((videoId, index) => {
      map.set(Number(videoId), jobQueries[index]?.data)
    })
    return map
  }, [analysisJobs, jobQueries])

  const {
    data: videos,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: pendingVideosKey(),
    queryFn: () => listVideos('pending'),
    refetchInterval: anyActive ? LIST_POLL_MS : false,
  })

  const analyzing = useMemo(() => videos?.filter((v) => v.status === 'analyzing') ?? [], [videos])
  const pending = useMemo(() => videos?.filter((v) => v.status !== 'analyzing') ?? [], [videos])

  // 清單裡還有 analyzing 的影片，就表示一定有工作在跑，即使我們還沒追蹤到它
  // （剛重新整理過）——這時要用較密的節奏去問，才接得回來。
  const { data: activeJobs } = useQuery({
    queryKey: activeJobsKey('analysis'),
    queryFn: () => listActiveJobs('analysis'),
    refetchInterval: analyzing.length > 0 && !anyActive ? LIST_POLL_MS : ACTIVE_JOBS_DISCOVERY_MS,
  })

  useEffect(() => {
    if (!activeJobs) return
    // 這裡就是 effect 的正當用法：把外部系統（後端 jobs 表）的狀態同步進來。
    // 不能改成 render 期間推導——job 一到終態就離開 activeJobs，推導的話會連
    // 帶消失，「✓ 分析完成」與完成通知都跳不出來，所以必須累積在 state 裡。
    // oxlint-disable-next-line react/set-state-in-effect
    setAnalysisJobs((prev) => {
      const next = { ...prev }
      let changed = false
      for (const job of activeJobs) {
        if (job.video_id === null || next[job.video_id] === job.id) continue
        next[job.video_id] = job.id
        changed = true
      }
      // 沒有新東西就回傳原本的物件，避免每次輪詢都產生新 reference 觸發重繪。
      return changed ? next : prev
    })
  }, [activeJobs])

  // 影片標題快照，理由見 SettledAnalysis。
  const titleByVideoId = useRef<Record<number, string>>({})
  useEffect(() => {
    for (const video of videos ?? []) titleByVideoId.current[video.id] = video.title
  }, [videos])

  useJobSettlement(
    jobQueries.map((query) => query.data),
    (settled) =>
      onSettled(
        settled.map((job) => ({
          job,
          title: (job.video_id !== null && titleByVideoId.current[job.video_id]) || '影片',
        })),
      ),
  )

  /** 開始追蹤一批剛送出的工作（video_id -> job_id）。 */
  const track = useCallback((jobsByVideoId: Record<number, number>) => {
    setAnalysisJobs((prev) => ({ ...prev, ...jobsByVideoId }))
  }, [])

  return {
    /** 正在分析的影片（清單上自成一段）。 */
    analyzing,
    /** 還在等的影片。 */
    pending,
    /** 兩段都空＝這頁沒有任何影片。 */
    isEmpty: analyzing.length === 0 && pending.length === 0,
    isLoading,
    isError,
    refetch,
    /** 某支影片目前追蹤中的工作；沒在追蹤就是 undefined。 */
    jobFor: (videoId: number) => jobByVideoId.get(videoId),
    track,
  }
}
