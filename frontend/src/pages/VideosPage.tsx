import { useCallback, useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { analyzeVideo, deleteVideo, downloadYoutube, listVideos, uploadVideo } from '../api/client'
import { ApiError } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { formatDateTime, formatDuration } from '../lib/format'
import { useJobPolling, useJobsPolling } from '../lib/useJobPolling'

const SOURCE_LABEL: Record<string, string> = { youtube: 'YouTube', local: '本機' }

/** 「影片與分析」頁面，對齊 ui/video_tab.py：新增影片（YouTube 下載／本機
 * 上傳）、待分析影片列表、開始分析，見
 * docs/07-ui-structure-and-features.md 6.1 節與
 * docs/09-web-ui-migration-plan.md Phase 3「上傳與分析任務」（本階段風險
 * 最高的一步：multipart 上傳進度 + job 輪詢兩個新模式）。 */
export function VideosPage() {
  const queryClient = useQueryClient()
  const { data: pending } = useQuery({ queryKey: ['videos', 'pending'], queryFn: () => listVideos('pending') })

  const [url, setUrl] = useState('')
  const [downloadJobId, setDownloadJobId] = useState<number | null>(null)
  const [downloadError, setDownloadError] = useState('')
  const [uploadPercent, setUploadPercent] = useState<number | null>(null)
  const [uploadError, setUploadError] = useState('')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [analysisJobs, setAnalysisJobs] = useState<Record<number, number>>({}) // video_id -> job_id
  const [rejectedNote, setRejectedNote] = useState('')

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
  const downloadActive = downloadMutation.isPending || (downloadJob ? downloadJob.status === 'running' || downloadJob.status === 'queued' : false)

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
  const jobByVideoId = new Map<number, (typeof jobQueries)[number]['data']>()
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

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteVideo(id),
    onSuccess: invalidateAfterChange,
  })

  const onRemoveClicked = async () => {
    const titles = [...selected].map((id) => pending?.find((v) => v.id === id)?.title ?? String(id))
    const preview = titles.slice(0, 3).join('、') + (titles.length > 3 ? '…' : '')
    if (!window.confirm(`確定要移除「${preview}」共 ${selected.size} 支影片，並刪除已下載的檔案嗎？`)) return
    for (const id of selected) {
      await deleteMutation.mutateAsync(id)
    }
    setSelected(new Set())
  }

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="rounded-lg border border-border bg-card p-4">
        <h2 className="mb-3 text-base font-bold">新增影片</h2>

        <label className="mb-1 block text-sm text-text-secondary">YouTube 網址</label>
        <form onSubmit={onDownloadSubmit} className="flex gap-2">
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={downloadActive}
            className="flex-1 rounded border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={downloadActive}
            className="rounded bg-primary px-4 py-2 text-sm font-bold text-white disabled:opacity-40"
          >
            下載影片
          </button>
        </form>

        <div className="mt-4 flex items-center gap-3">
          <label className="cursor-pointer rounded border border-border px-3 py-1.5 text-sm font-bold">
            選擇本機影片
            <input
              type="file"
              accept=".mp4,.mov,.mkv,.webm"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) onFileSelected(file)
                e.target.value = ''
              }}
            />
          </label>
          <span className="text-sm text-text-secondary">支援格式：MP4、MOV、MKV、WebM</span>
        </div>

        {(downloadActive || downloadJob) && (
          <div className="mt-3 h-2 overflow-hidden rounded bg-[#E4E7EC]">
            <div
              className="h-full bg-primary transition-all"
              style={{ width: `${downloadJob?.progress_percent ?? 0}%` }}
            />
          </div>
        )}
        {uploadPercent !== null && (
          <div className="mt-3 h-2 overflow-hidden rounded bg-[#E4E7EC]">
            <div className="h-full bg-primary transition-all" style={{ width: `${uploadPercent}%` }} />
          </div>
        )}

        <p className="mt-2 text-sm text-text-secondary">
          {downloadError && <span className="text-error">{downloadError}</span>}
          {!downloadError && downloadJob && downloadJob.status === 'running' && (downloadJob.progress_message ?? '下載中…')}
          {!downloadError && downloadJob?.status === 'failed' && <span className="text-error">下載失敗：{downloadJob.error_message}</span>}
          {uploadError && <span className="text-error">{uploadError}</span>}
          {uploadPercent !== null && `上傳中… ${uploadPercent.toFixed(0)}%`}
          {!downloadError && !downloadJob && uploadPercent === null && !uploadError && '尚未開始'}
        </p>
      </div>

      <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-card p-4">
        <h2 className="mb-3 text-base font-bold">待分析影片（{pending?.length ?? 0}）</h2>
        <div className="min-h-0 flex-1 overflow-auto">
          {!pending || pending.length === 0 ? (
            <EmptyState title="目前沒有待分析影片" hints={['可貼上 YouTube 網址或選擇本機影片']} />
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-[#F0F2F5] text-xs text-text-secondary">
                <tr>
                  <th className="w-8 px-2 py-2" />
                  <th className="px-2 py-2">影片名稱</th>
                  <th className="px-2 py-2">長度</th>
                  <th className="px-2 py-2">來源</th>
                  <th className="px-2 py-2">加入時間</th>
                  <th className="px-2 py-2">狀態</th>
                </tr>
              </thead>
              <tbody>
                {pending.map((v) => {
                  const job = jobByVideoId.get(v.id)
                  const statusText = job
                    ? job.status === 'completed'
                      ? '✓ 分析完成'
                      : job.status === 'failed'
                        ? `分析失敗：${job.error_message}`
                        : job.status === 'running'
                          ? `${job.stage ?? '分析中'}…`
                          : '排隊中…'
                    : '等待分析'
                  return (
                    <tr key={v.id} className="border-b border-border last:border-0">
                      <td className="px-2 py-2">
                        <input type="checkbox" checked={selected.has(v.id)} onChange={() => toggleSelected(v.id)} />
                      </td>
                      <td className="px-2 py-2">{v.title}</td>
                      <td className="px-2 py-2">{formatDuration(v.duration_sec)}</td>
                      <td className="px-2 py-2">{SOURCE_LABEL[v.source] ?? v.source}</td>
                      <td className="px-2 py-2">{formatDateTime(v.created_at)}</td>
                      <td className="px-2 py-2">{statusText}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        <div className="mt-3 flex gap-2">
          <button
            disabled={selected.size === 0}
            onClick={onAnalyzeClicked}
            className="rounded border border-border px-3 py-1.5 text-sm font-bold disabled:opacity-40"
          >
            開始分析
          </button>
          <button
            disabled={selected.size === 0}
            onClick={onRemoveClicked}
            className="rounded border border-border px-3 py-1.5 text-sm font-bold disabled:opacity-40"
          >
            移除
          </button>
        </div>
        {rejectedNote && <p className="mt-2 text-sm text-error">{rejectedNote}</p>}
      </div>
    </div>
  )
}
