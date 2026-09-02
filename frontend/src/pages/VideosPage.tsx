import { useCallback, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { MonitorPlay } from 'lucide-react'
import { analyzeVideo, deleteVideo, retryJob } from '../api/client'
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
import { isActive } from '../lib/jobStatus'
import { libraryVideosKey, pendingVideosKey, statsKey } from '../lib/queryKeys'
import { useAnalysisQueue } from '../lib/useAnalysisQueue'
import { useToast } from '../lib/useToast'

const SOURCE_LABEL: Record<string, string> = { youtube: 'YouTube', local: '本機' }

/** 一次最多勾選幾支送分析。分析是全站唯一會花錢的觸發點，而
 * `analyzer.BUDGET_USD`（US$0.80）是**每支影片各自計算**的，沒有批次層級的
 * 總量上限（見 docs/05 §8.12 的上限對照表），所以在送出前先用勾選數把單批的
 * 成本天花板壓在 5×$0.80 以內。
 *
 * 這是 UI 層的節流，不是強制約束：`POST /api/v1/videos/{id}/analyze` 一次只
 * 收一支影片、本身沒有批次概念，job_manager 也不限制排隊數量，所以直接打 API
 * 仍然可以無限送。 */
const MAX_BATCH_SELECTION = 5

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

/** 「影片分析」頁面：待分析影片列表、開始分析、移除，見
 * docs/archive/07-ui-structure-and-features.md 6.1 節與
 * docs/archive/09-web-ui-migration-plan.md Phase 3「上傳與分析任務」。
 *
 * **這頁不再有「新增影片」區塊**：影片一律從「新增影片」頁的卡片按
 * 「加入待分析」收進來，本機上傳也一併移除（見 docs/05 §8.5）。這頁的職責
 * 收斂成「決定哪些收進來的影片要送分析」——也是全站唯一會花錢的觸發點。
 *
 * 清單收的是 pending＋analyzing 兩種狀態（後端 `?status=pending`）。分析中的
 * 影片一定要留在這裡：videos 表的四個狀態原本被切成「pending 在這頁、
 * analyzed／failed 在影片庫」，中間的 analyzing 兩邊都不收，影片會在整段分析
 * 期間（實測 43～93 秒）從畫面上完全消失，連進度顯示一起帶走。 */
export function VideosPage() {
  const queryClient = useQueryClient()
  const toast = useToast()

  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [rejectedNote, setRejectedNote] = useState('')
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false)

  const invalidateAfterChange = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: pendingVideosKey() })
    queryClient.invalidateQueries({ queryKey: libraryVideosKey() })
    queryClient.invalidateQueries({ queryKey: statsKey() })
  }, [queryClient])

  // 待分析清單與跑在它上面的分析工作，見 lib/useAnalysisQueue.ts——兩者的輪詢
  // 節奏互為輸入，所以是同一個 hook 管的。
  //
  // 每支跑完的影片各跳一則通知，但清單／統計一輪只刷一次，不是每支各刷一次。
  const queue = useAnalysisQueue((settled) => {
    for (const { job, title } of settled) {
      if (job.status === 'completed') toast.show(`「${title}」分析完成，已移到影片庫`, 'success')
      else toast.show(`「${title}」分析失敗：${job.error_message ?? '未知錯誤'}`, 'error')
    }
    invalidateAfterChange()
  })

  // 兩段合起來就是這頁的全部影片。只用來由 id 反查標題（送出分析被拒、或
  // 確認移除時要說出是哪幾支），不決定畫面上的排列。
  const allRows = [...queue.analyzing, ...queue.pending]

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
        const title = allRows.find((v) => v.id === id)?.title ?? String(id)
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
      queue.track(newJobs)
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
    queue.track({ [videoId]: newJob.id })
    invalidateAfterChange()
  }

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteVideo(id),
    onSuccess: invalidateAfterChange,
  })

  const atSelectionLimit = selected.size >= MAX_BATCH_SELECTION
  const selectedTitles = [...selected].map((id) => allRows.find((v) => v.id === id)?.title ?? String(id))
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
    const job = queue.jobFor(v.id)
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
          待分析影片（{queue.pending.length}）
          {queue.analyzing.length > 0 && (
            <span className="ml-2 text-sm font-normal text-primary">分析中 {queue.analyzing.length}</span>
          )}
        </h2>
        <div className="min-h-0 flex-1 overflow-auto" aria-busy={queue.isLoading}>
          {queue.isLoading ? (
            <LoadingSkeleton variant="list-item" count={3} />
          ) : queue.isError ? (
            <ErrorState title="載入待分析影片失敗" onRetry={() => queue.refetch()} />
          ) : queue.isEmpty ? (
            // 這頁已經沒有新增影片的入口，空狀態必須直接把人帶去唯一的入口，
            // 否則會變成無路可走的死路。
            <EmptyState
              title="目前沒有待分析影片"
              hints={['到「新增影片」頁找影片，按卡片上的「加入待分析」就會出現在這裡']}
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
              {queue.analyzing.length > 0 && (
                <>
                  <SectionHeading text={`分析中（${queue.analyzing.length}）`} />
                  {queue.analyzing.map(renderRow)}
                </>
              )}
              {queue.pending.length > 0 && (
                <>
                  {queue.analyzing.length > 0 && <SectionHeading text={`待分析（${queue.pending.length}）`} />}
                  {queue.pending.map(renderRow)}
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
