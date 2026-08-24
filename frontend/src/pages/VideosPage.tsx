import { useCallback, useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { analyzeVideo, deleteVideo, downloadYoutube, listVideos, retryJob, uploadVideo } from '../api/client'
import { ApiError } from '../api/types'
import type { Job } from '../api/types'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Dropzone } from '../components/Dropzone'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { LoadingSkeleton } from '../components/LoadingSkeleton'
import { SegmentedControl } from '../components/SegmentedControl'
import { VideoListItem } from '../components/VideoListItem'
import { formatDateTime, formatDuration, formatElapsed } from '../lib/format'
import { useJobPolling, useJobsPolling } from '../lib/useJobPolling'
import { useToast } from '../lib/useToast'

const SOURCE_LABEL: Record<string, string> = { youtube: 'YouTube', local: '本機' }

const SOURCE_OPTIONS = [
  { value: 'youtube' as const, label: 'YouTube 網址' },
  { value: 'local' as const, label: '本機影片' },
]

function jobStatusInfo(job: Job | undefined): { text: string; kind: 'success' | 'error' | 'primary' | 'neutral' } {
  if (!job) return { text: '等待分析', kind: 'neutral' }
  if (job.status === 'completed') return { text: '✓ 分析完成', kind: 'success' }
  if (job.status === 'failed') return { text: '分析失敗', kind: 'error' }
  if (job.status === 'running') return { text: job.stage ?? '分析中', kind: 'primary' }
  return { text: '排隊中', kind: 'neutral' }
}

/** 「影片與分析」頁面，對齊 ui/video_tab.py：新增影片（YouTube 下載／本機
 * 上傳）、待分析影片列表、開始分析，見
 * docs/07-ui-structure-and-features.md 6.1 節與
 * docs/09-web-ui-migration-plan.md Phase 3「上傳與分析任務」（本階段風險
 * 最高的一步：multipart 上傳進度 + job 輪詢兩個新模式）。 */
export function VideosPage() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const {
    data: pending,
    isLoading: pendingLoading,
    isError: pendingError,
    refetch: refetchPending,
  } = useQuery({ queryKey: ['videos', 'pending'], queryFn: () => listVideos('pending') })

  const [sourceMode, setSourceMode] = useState<'youtube' | 'local'>('youtube')
  const [url, setUrl] = useState('')
  const [downloadJobId, setDownloadJobId] = useState<number | null>(null)
  const [downloadError, setDownloadError] = useState('')
  const [uploadPercent, setUploadPercent] = useState<number | null>(null)
  const [uploadError, setUploadError] = useState('')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [analysisJobs, setAnalysisJobs] = useState<Record<number, number>>({}) // video_id -> job_id
  const [rejectedNote, setRejectedNote] = useState('')
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false)

  const invalidateAfterChange = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['videos', 'pending'] })
    queryClient.invalidateQueries({ queryKey: ['videos', 'library'] })
    queryClient.invalidateQueries({ queryKey: ['stats'] })
  }, [queryClient])

  // --- YouTube 下載 ---
  const downloadMutation = useMutation({
    mutationFn: (u: string) => downloadYoutube(u),
    onSuccess: (job) => {
      setDownloadError('')
      setDownloadJobId(job.id)
    },
    onError: (err: Error) => setDownloadError(err.message),
  })
  const downloadJobQuery = useJobPolling(downloadJobId)
  const downloadJob = downloadJobQuery.data
  const downloadActive =
    downloadMutation.isPending || (downloadJob ? downloadJob.status === 'running' || downloadJob.status === 'queued' : false)

  useEffect(() => {
    if (downloadJob?.status === 'completed') {
      // downloadJob 的來源是輪詢查詢（外部系統），不是使用者觸發的 DOM
      // 事件，這裡是 TanStack Query 目前推薦的「回應查詢狀態變化」寫法
      // （v5 拿掉了 useQuery 的 onSuccess callback）；setDownloadJobId(null)
      // 之後 useJobPolling(null) 會停用查詢，不會再次觸發，不會連續重渲染。
      // oxlint-disable-next-line react/set-state-in-effect
      setDownloadJobId(null)
      setUrl('')
      invalidateAfterChange()
    }
  }, [downloadJob?.status, invalidateAfterChange])

  const onDownloadSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!url.trim()) {
      setDownloadError('請輸入 YouTube 網址')
      return
    }
    downloadMutation.mutate(url.trim())
  }

  // --- 本機上傳 ---
  const onFileSelected = (file: File) => {
    setUploadError('')
    setUploadPercent(0)
    uploadVideo(file, setUploadPercent)
      .then(() => {
        setUploadPercent(null)
        invalidateAfterChange()
      })
      .catch((err: Error) => {
        setUploadPercent(null)
        setUploadError(err.message)
      })
  }

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
      <Card>
        <h2 className="mb-3 text-base font-bold text-text-primary">新增影片</h2>
        <SegmentedControl options={SOURCE_OPTIONS} value={sourceMode} onChange={setSourceMode} />

        {sourceMode === 'youtube' ? (
          <form onSubmit={onDownloadSubmit} className="mt-3 flex gap-2">
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              disabled={downloadActive}
              placeholder="貼上 YouTube 影片網址"
              className="flex-1 rounded-xl border border-border bg-card px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-primary focus:outline-none disabled:opacity-60"
            />
            <Button type="submit" variant="primary" disabled={downloadActive} icon={<Download className="h-4 w-4" />}>
              下載影片
            </Button>
          </form>
        ) : (
          <div className="mt-3">
            <Dropzone onFileSelected={onFileSelected} disabled={uploadPercent !== null} hint="支援格式：MP4、MOV、MKV、WebM" />
          </div>
        )}

        {(downloadActive || downloadJob) && (
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-sand">
            <div
              className="h-full bg-primary transition-all"
              style={{ width: `${downloadJob?.progress_percent ?? 0}%` }}
            />
          </div>
        )}
        {uploadPercent !== null && (
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-sand">
            <div className="h-full bg-primary transition-all" style={{ width: `${uploadPercent}%` }} />
          </div>
        )}

        {(downloadError || uploadError || downloadJob || uploadPercent !== null) && (
          <p className="mt-2 text-sm text-text-secondary" aria-live="polite">
            {downloadError && <span className="text-error">{downloadError}</span>}
            {!downloadError && downloadJob && downloadJob.status === 'running' && (downloadJob.progress_message ?? '下載中…')}
            {!downloadError && downloadJob?.status === 'failed' && (
              <span className="text-error">下載失敗：{downloadJob.error_message}</span>
            )}
            {uploadError && <span className="text-error">{uploadError}</span>}
            {uploadPercent !== null && `上傳中… ${uploadPercent.toFixed(0)}%`}
          </p>
        )}
      </Card>

      <Card className="flex min-h-0 flex-1 flex-col">
        <h2 className="mb-1 text-base font-bold text-text-primary">待分析影片（{pending?.length ?? 0}）</h2>
        <div className="min-h-0 flex-1 overflow-auto" aria-busy={pendingLoading}>
          {pendingLoading ? (
            <LoadingSkeleton variant="list-item" count={3} />
          ) : pendingError ? (
            <ErrorState title="載入待分析影片失敗" onRetry={() => refetchPending()} />
          ) : !pending || pending.length === 0 ? (
            <EmptyState title="目前沒有待分析影片" hints={['可貼上 YouTube 網址或選擇本機影片']} />
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
