import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { MonitorPlay } from 'lucide-react'
import { analyzeVideo, deleteVideo, listActiveJobs, listVideos, retryJob } from '../api/client'
import { ApiError } from '../api/types'
import type { Job, Video } from '../api/types'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { LoadingSkeleton } from '../components/LoadingSkeleton'
import { VideoListItem } from '../components/VideoListItem'
import { formatDateTime, formatDuration, formatElapsed } from '../lib/format'
import { isActive, isTerminal } from '../lib/jobStatus'
import { activeJobsKey, libraryVideosKey, pendingVideosKey, statsKey } from '../lib/queryKeys'
import { useJobsPolling } from '../lib/useJobPolling'
import { useToast } from '../lib/useToast'

const SOURCE_LABEL: Record<string, string> = { youtube: 'YouTube', local: '本機' }

/** 一次最多勾選幾支送分析。分析是全站唯一會花錢的觸發點，而
 * `analyzer.BUDGET_USD`（US$0.80）是**每支影片各自計算**的，沒有批次層級的
 * 總量上限（見 docs/11 §8.12 的上限對照表），所以在送出前先用勾選數把單批的
 * 成本天花板壓在 5×$0.80 以內。
 *
 * 這是 UI 層的節流，不是強制約束：`POST /api/v1/videos/{id}/analyze` 一次只
 * 收一支影片、本身沒有批次概念，job_manager 也不限制排隊數量，所以直接打 API
 * 仍然可以無限送。 */
const MAX_BATCH_SELECTION = 5

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

function jobStatusInfo(
  video: Video,
  job: Job | undefined,
): { text: string; kind: 'success' | 'error' | 'primary' | 'neutral' } {
  // 影片自己的 status 優先於 job：重新整理後 job 還沒撈回來時，
  // `status === 'analyzing'` 仍然要顯示成分析中，不能退回「等待分析」。
  if (job?.status === 'completed') return { text: '✓ 分析完成', kind: 'success' }
  if (job?.status === 'failed') return { text: '分析失敗', kind: 'error' }
  if (video.status === 'analyzing' || job?.status === 'running') {
    return { text: job?.stage ?? video.pipeline_stage ?? '分析中', kind: 'primary' }
  }
  if (job?.status === 'queued') return { text: '排隊中', kind: 'neutral' }
  return { text: '等待分析', kind: 'neutral' }
}

/** 「影片與分析」頁面：待分析影片列表、開始分析、移除，見
 * docs/07-ui-structure-and-features.md 6.1 節與
 * docs/09-web-ui-migration-plan.md Phase 3「上傳與分析任務」。
 *
 * **這頁不再有「新增影片」區塊**：影片一律從「YouTube 搜尋」頁的卡片按
 * 「加入待分析」收進來，本機上傳也一併移除（見 docs/11 §8.5）。這頁的職責
 * 收斂成「決定哪些收進來的影片要送分析」——也是全站唯一會花錢的觸發點。
 *
 * 清單收的是 pending＋analyzing 兩種狀態（後端 `?status=pending`）。分析中的
 * 影片一定要留在這裡：videos 表的四個狀態原本被切成「pending 在這頁、
 * analyzed／failed 在影片庫」，中間的 analyzing 兩邊都不收，影片會在整段分析
 * 期間（實測 43～93 秒）從畫面上完全消失，連進度顯示一起帶走。 */
export function VideosPage() {
  const queryClient = useQueryClient()
  const toast = useToast()

  // 追蹤中的分析 job：video_id -> job_id。兩個來源——按下「開始分析」當下的
  // 回應，以及 activeJobsQuery 從後端撈回來的進行中工作（重新整理後靠它接回
  // 來）。已完成的 job 不從這裡移除：useJobsPolling 對終態 job 會停止輪詢，
  // 留著不花成本，而且要留著才顯示得出「✓ 分析完成」與失敗時的重試。
  const [analysisJobs, setAnalysisJobs] = useState<Record<number, number>>({})
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [rejectedNote, setRejectedNote] = useState('')
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false)

  const trackedJobIds = useMemo(() => Object.values(analysisJobs), [analysisJobs])
  const jobQueries = useJobsPolling(trackedJobIds)
  const jobByVideoId = new Map<number, Job | undefined>()
  Object.keys(analysisJobs).forEach((videoId, idx) => {
    jobByVideoId.set(Number(videoId), jobQueries[idx]?.data)
  })
  const anyAnalysisActive = jobQueries.some((q) => isActive(q.data?.status))

  const {
    data: pending,
    isLoading: pendingLoading,
    isError: pendingError,
    refetch: refetchPending,
  } = useQuery({
    queryKey: pendingVideosKey(),
    queryFn: () => listVideos('pending'),
    refetchInterval: anyAnalysisActive ? LIST_POLL_MS : false,
  })

  const analyzingRows = useMemo(() => pending?.filter((v) => v.status === 'analyzing') ?? [], [pending])
  const pendingRows = useMemo(() => pending?.filter((v) => v.status !== 'analyzing') ?? [], [pending])

  // 清單裡還有 analyzing 的影片，就表示一定有工作在跑，即使我們還沒追蹤到它
  // （剛重新整理過）——這時要用較密的節奏去問，才接得回來。
  const { data: activeJobs } = useQuery({
    queryKey: activeJobsKey('analysis'),
    queryFn: () => listActiveJobs('analysis'),
    refetchInterval: analyzingRows.length > 0 && !anyAnalysisActive ? LIST_POLL_MS : ACTIVE_JOBS_DISCOVERY_MS,
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

  const invalidateAfterChange = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: pendingVideosKey() })
    queryClient.invalidateQueries({ queryKey: libraryVideosKey() })
    queryClient.invalidateQueries({ queryKey: statsKey() })
  }, [queryClient])

  // 影片標題快照：job 結束時要跳 toast 說「哪一支好了」，但那一刻清單馬上會
  // 重取、該影片已經移去影片庫，從 `pending` 裡就查不到標題了。
  const titleByVideoId = useRef<Record<number, string>>({})
  useEffect(() => {
    for (const v of pending ?? []) titleByVideoId.current[v.id] = v.title
  }, [pending])

  // 每個 job 只通知一次。用 ref 而不是 state：它只是去重用的備忘錄，
  // 寫進去不需要（也不該）觸發重繪。
  const notifiedJobIds = useRef<Set<number>>(new Set())
  useEffect(() => {
    let settledAny = false
    for (const query of jobQueries) {
      const job = query.data
      if (!job || !isTerminal(job.status)) continue
      if (notifiedJobIds.current.has(job.id)) continue
      notifiedJobIds.current.add(job.id)
      settledAny = true
      const title = (job.video_id !== null && titleByVideoId.current[job.video_id]) || '影片'
      if (job.status === 'completed') toast.show(`「${title}」分析完成，已移到影片庫`, 'success')
      else toast.show(`「${title}」分析失敗：${job.error_message ?? '未知錯誤'}`, 'error')
    }
    // 一輪只刷一次清單／統計，不是每支影片各刷一次。
    if (settledAny) invalidateAfterChange()
  }, [jobQueries, invalidateAfterChange, toast])

  // --- 待分析清單 ---
  const toggleSelected = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
        return next
      }
      // 已達上限就不再加選。畫面上未勾選的 checkbox 這時已經是 disabled，
      // 這裡是第二道防線，確保狀態本身不可能超過上限。
      if (next.size >= MAX_BATCH_SELECTION) return prev
      next.add(id)
      return next
    })
  }

  const analyzeMutation = useMutation({
    mutationFn: (id: number) => analyzeVideo(id),
  })

  const onAnalyzeClicked = async () => {
    setRejectedNote('')
    const ids = [...selected]
    const rejected: string[] = []
    const newJobs: Record<number, number> = {}
    for (const id of ids) {
      try {
        const job = await analyzeMutation.mutateAsync(id)
        newJobs[id] = job.id
      } catch (err) {
        const title = pending?.find((v) => v.id === id)?.title ?? String(id)
        if (err instanceof ApiError && err.code === 'DURATION_LIMIT_EXCEEDED') {
          rejected.push(title)
        } else {
          rejected.push(`${title}（${err instanceof Error ? err.message : '未知錯誤'}）`)
        }
      }
    }
    if (rejected.length > 0) {
      setRejectedNote(`「${rejected.join('、')}」無法送出分析，超過長度限制或已在分析中。`)
    }
    if (Object.keys(newJobs).length > 0) {
      setAnalysisJobs((prev) => ({ ...prev, ...newJobs }))
      // 送出去的取消勾選，否則它們會一路保持勾選狀態，「移除」按鈕還亮著，
      // 一按就把正在分析的影片連檔案一起刪掉。
      setSelected((prev) => new Set([...prev].filter((id) => !(id in newJobs))))
      // 後端的 status 是分析執行緒起來之後才寫成 analyzing，這裡先刷一次讓
      // 那一列盡快換成「分析中」；沒趕上也沒關係，輪詢會補上。
      invalidateAfterChange()
    }
  }

  const retryMutation = useMutation({ mutationFn: (jobId: number) => retryJob(jobId) })
  const onRetryClicked = async (videoId: number, jobId: number) => {
    const newJob = await retryMutation.mutateAsync(jobId)
    setAnalysisJobs((prev) => ({ ...prev, [videoId]: newJob.id }))
    invalidateAfterChange()
  }

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteVideo(id),
    onSuccess: invalidateAfterChange,
  })

  const atSelectionLimit = selected.size >= MAX_BATCH_SELECTION
  const selectedTitles = [...selected].map((id) => pending?.find((v) => v.id === id)?.title ?? String(id))
  const deletePreview = selectedTitles.slice(0, 3).join('、') + (selectedTitles.length > 3 ? '…' : '')

  const onConfirmRemove = async () => {
    setConfirmDeleteOpen(false)
    const count = selected.size
    for (const id of selected) {
      await deleteMutation.mutateAsync(id)
    }
    setSelected(new Set())
    toast.show(`已移除 ${count} 支影片`, 'success')
  }

  const renderRow = (v: Video) => {
    const job = jobByVideoId.get(v.id)
    const analyzing = v.status === 'analyzing' || isActive(job?.status)
    const status = jobStatusInfo(v, job)
    return (
      <VideoListItem
        key={v.id}
        video={v}
        checked={selected.has(v.id)}
        // 分析中的影片不能被勾選：勾選的用途只有「送分析」與「移除」，前者
        // 後端會回 409，後者會在分析途中把檔案刪掉。
        checkboxDisabled={analyzing || (!selected.has(v.id) && atSelectionLimit)}
        checkboxDisabledReason={analyzing ? '分析中，無法勾選' : `一次最多勾選 ${MAX_BATCH_SELECTION} 支`}
        onCheckedChange={() => toggleSelected(v.id)}
        meta={
          <>
            {SOURCE_LABEL[v.source] ?? v.source} ・ {formatDuration(v.duration_sec)} ・{' '}
            {formatDateTime(v.created_at)}
          </>
        }
        trailing={
          <div className="flex flex-col items-end gap-1">
            <Badge text={status.text} kind={status.kind} />
            {/* 已耗時要有 job 才算得出來（started_at 在 job 上）。剛重新整理、
                還沒把 job 接回來的那幾秒只顯示狀態，不要拿 null 去算出一個
                停在 0:00 的假計時。 */}
            {analyzing && job && (
              <span className="text-xs text-text-muted">
                {job.progress_percent === null ? '' : `${job.progress_percent}% ・ `}
                {formatElapsed(job.started_at)}
              </span>
            )}
            {job?.status === 'failed' && (
              <>
                {job.error_message && (
                  <span className="max-w-[200px] truncate text-xs text-error" title={job.error_message}>
                    {job.error_message}
                  </span>
                )}
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={retryMutation.isPending}
                  onClick={() => onRetryClicked(v.id, job.id)}
                >
                  重試
                </Button>
              </>
            )}
          </div>
        }
      />
    )
  }

  return (
    <div className="flex h-full flex-col gap-4">
      <Card className="flex min-h-0 flex-1 flex-col">
        <h2 className="mb-1 text-base font-bold text-text-primary">
          待分析影片（{pendingRows.length}）
          {analyzingRows.length > 0 && (
            <span className="ml-2 text-sm font-normal text-primary">分析中 {analyzingRows.length}</span>
          )}
        </h2>
        <div className="min-h-0 flex-1 overflow-auto" aria-busy={pendingLoading}>
          {pendingLoading ? (
            <LoadingSkeleton variant="list-item" count={3} />
          ) : pendingError ? (
            <ErrorState title="載入待分析影片失敗" onRetry={() => refetchPending()} />
          ) : !pending || pending.length === 0 ? (
            // 這頁已經沒有新增影片的入口，空狀態必須直接把人帶去唯一的入口，
            // 否則會變成無路可走的死路。
            <EmptyState
              title="目前沒有待分析影片"
              hints={['到「YouTube 搜尋」頁找影片，按卡片上的「加入待分析」就會出現在這裡']}
              icon={<MonitorPlay className="h-8 w-8" aria-hidden="true" />}
              action={
                <Link
                  to="/youtube"
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-primary px-4 text-sm font-bold text-white transition-colors hover:bg-primary-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                >
                  <MonitorPlay className="h-4 w-4" aria-hidden="true" />
                  去 YouTube 搜尋
                </Link>
              }
            />
          ) : (
            // 分析中的排在最上面自成一段：它們是「現在正在發生的事」，而且不可
            // 勾選，混在待分析裡會讓人以為是漏勾了。只有兩段都有東西時才需要
            // 標題把它們分開。
            <>
              {analyzingRows.length > 0 && (
                <>
                  <SectionHeading text={`分析中（${analyzingRows.length}）`} />
                  {analyzingRows.map(renderRow)}
                </>
              )}
              {pendingRows.length > 0 && (
                <>
                  {analyzingRows.length > 0 && <SectionHeading text={`待分析（${pendingRows.length}）`} />}
                  {pendingRows.map(renderRow)}
                </>
              )}
            </>
          )}
        </div>

        <div className="mt-3 flex gap-2">
          <Button variant="primary" disabled={selected.size === 0} onClick={onAnalyzeClicked}>
            開始分析
          </Button>
          <Button variant="secondary" disabled={selected.size === 0} onClick={() => setConfirmDeleteOpen(true)}>
            移除
          </Button>
          <p className="self-center text-sm text-text-secondary" aria-live="polite">
            已選 {selected.size} / {MAX_BATCH_SELECTION}
            {atSelectionLimit && '（已達一次可送出的上限）'}
          </p>
        </div>
        {rejectedNote && (
          <p className="mt-2 text-sm text-error" aria-live="polite">
            {rejectedNote}
          </p>
        )}
      </Card>

      <ConfirmDialog
        open={confirmDeleteOpen}
        title="確認移除影片"
        description={`確定要移除「${deletePreview}」共 ${selected.size} 支影片，並刪除已下載的檔案嗎？`}
        destructive
        confirmLabel="移除"
        onConfirm={onConfirmRemove}
        onCancel={() => setConfirmDeleteOpen(false)}
      />
    </div>
  )
}

/** 清單內的分段標題。sticky 是為了長清單捲動時仍看得出現在在哪一段。 */
function SectionHeading({ text }: { text: string }) {
  return (
    <p className="sticky top-0 z-10 bg-card py-1.5 text-xs font-bold uppercase tracking-wide text-text-muted">
      {text}
    </p>
  )
}
