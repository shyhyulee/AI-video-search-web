import { useCallback, useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { MonitorPlay } from 'lucide-react'
import { analyzeVideo, deleteVideo, listVideos, retryJob } from '../api/client'
import { ApiError } from '../api/types'
import type { Job } from '../api/types'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { LoadingSkeleton } from '../components/LoadingSkeleton'
import { VideoListItem } from '../components/VideoListItem'
import { formatDateTime, formatDuration, formatElapsed } from '../lib/format'
import { useJobsPolling } from '../lib/useJobPolling'
import { useToast } from '../lib/useToast'

const SOURCE_LABEL: Record<string, string> = { youtube: 'YouTube', local: '本機' }

function jobStatusInfo(job: Job | undefined): { text: string; kind: 'success' | 'error' | 'primary' | 'neutral' } {
  if (!job) return { text: '等待分析', kind: 'neutral' }
  if (job.status === 'completed') return { text: '✓ 分析完成', kind: 'success' }
  if (job.status === 'failed') return { text: '分析失敗', kind: 'error' }
  if (job.status === 'running') return { text: job.stage ?? '分析中', kind: 'primary' }
  return { text: '排隊中', kind: 'neutral' }
}

/** 「影片與分析」頁面：待分析影片列表、開始分析、移除，見
 * docs/07-ui-structure-and-features.md 6.1 節與
 * docs/09-web-ui-migration-plan.md Phase 3「上傳與分析任務」。
 *
 * **這頁不再有「新增影片」區塊**：影片一律從「YouTube 搜尋」頁的卡片按
 * 「加入待分析」收進來，本機上傳也一併移除（見 docs/11 §8.5）。這頁的職責
 * 收斂成「決定哪些收進來的影片要送分析」——也是全站唯一會花錢的觸發點。 */
export function VideosPage() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const {
    data: pending,
    isLoading: pendingLoading,
    isError: pendingError,
    refetch: refetchPending,
  } = useQuery({ queryKey: ['videos', 'pending'], queryFn: () => listVideos('pending') })

  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [analysisJobs, setAnalysisJobs] = useState<Record<number, number>>({}) // video_id -> job_id
  const [rejectedNote, setRejectedNote] = useState('')
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false)

  const invalidateAfterChange = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['videos', 'pending'] })
    queryClient.invalidateQueries({ queryKey: ['videos', 'library'] })
    queryClient.invalidateQueries({ queryKey: ['stats'] })
  }, [queryClient])

  // --- 待分析清單 ---
  const toggleSelected = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
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
    }
  }

  const trackedJobIds = Object.values(analysisJobs)
  const jobQueries = useJobsPolling(trackedJobIds)
  const jobByVideoId = new Map<number, Job | undefined>()
  Object.entries(analysisJobs).forEach(([videoId, jobId], idx) => {
    void jobId
    jobByVideoId.set(Number(videoId), jobQueries[idx]?.data)
  })
  const anyAnalysisActive = jobQueries.some((q) => q.data && (q.data.status === 'queued' || q.data.status === 'running'))
  const allTrackedJobsSettled = trackedJobIds.length > 0 && jobQueries.every((q) => q.data)

  useEffect(() => {
    // 全部分析工作都到終態才做一次收尾（刷新清單／統計＋清空追蹤清單）；
    // 清空 analysisJobs 會讓 trackedJobIds.length 變回 0，下一輪 effect
    // 的條件自然不成立，不會重複觸發。
    if (!anyAnalysisActive && allTrackedJobsSettled) {
      invalidateAfterChange()
      // oxlint-disable-next-line react/set-state-in-effect
      setAnalysisJobs({})
    }
  }, [anyAnalysisActive, allTrackedJobsSettled, invalidateAfterChange])

  const retryMutation = useMutation({ mutationFn: (jobId: number) => retryJob(jobId) })
  const onRetryClicked = async (videoId: number, jobId: number) => {
    const newJob = await retryMutation.mutateAsync(jobId)
    setAnalysisJobs((prev) => ({ ...prev, [videoId]: newJob.id }))
  }

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteVideo(id),
    onSuccess: invalidateAfterChange,
  })

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

  return (
    <div className="flex h-full flex-col gap-4">
      <Card className="flex min-h-0 flex-1 flex-col">
        <h2 className="mb-1 text-base font-bold text-text-primary">待分析影片（{pending?.length ?? 0}）</h2>
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
            pending.map((v) => {
              const job = jobByVideoId.get(v.id)
              const status = jobStatusInfo(job)
              return (
                <VideoListItem
                  key={v.id}
                  video={v}
                  checked={selected.has(v.id)}
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
                      {job?.status === 'running' && (
                        <span className="text-xs text-text-muted">
                          {job.progress_percent !== null ? `${job.progress_percent}% ・ ` : ''}
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
            })
          )}
        </div>

        <div className="mt-3 flex gap-2">
          <Button variant="primary" disabled={selected.size === 0} onClick={onAnalyzeClicked}>
            開始分析
          </Button>
          <Button variant="secondary" disabled={selected.size === 0} onClick={() => setConfirmDeleteOpen(true)}>
            移除
          </Button>
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
