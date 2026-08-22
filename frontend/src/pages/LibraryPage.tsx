import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { getThumbnailUrl, listVideos, reanalyzeVideo, regenerateSummary } from '../api/client'
import type { Video } from '../api/types'
import { Badge } from '../components/Badge'
import { EmptyState } from '../components/EmptyState'
import { formatCost, formatDateTime, formatDuration } from '../lib/format'
import { useJobPolling } from '../lib/useJobPolling'

type FilterKind = 'all' | 'analyzed' | 'failed' | 'no_subtitle' | 'visual_only'
type SortColumn = 'title' | 'segment_count' | 'cost' | 'analyzed_at'

const FILTERS: { key: FilterKind; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'analyzed', label: '分析完成' },
  { key: 'failed', label: '分析失敗' },
  { key: 'no_subtitle', label: '無字幕' },
  { key: 'visual_only', label: '純畫面' },
]

const STATUS_LABEL: Record<string, string> = { analyzed: '分析完成', failed: '分析失敗' }

/** 「影片庫」頁面，對齊 ui/library_tab.py：篩選／排序列表 + 詳細資訊面板，
 * 見 docs/07-ui-structure-and-features.md 6.2 節。 */
export function LibraryPage() {
  const [filter, setFilter] = useState<FilterKind>('all')
  const [sortColumn, setSortColumn] = useState<SortColumn>('analyzed_at')
  const [sortReverse, setSortReverse] = useState(true)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [query, setQuery] = useState('')
  const navigate = useNavigate()

  const { data: videos } = useQuery({ queryKey: ['videos', 'library'], queryFn: () => listVideos() })

  const rows = useMemo(() => {
    if (!videos) return []
    let filtered = videos
    if (filter === 'analyzed') filtered = videos.filter((v) => v.status === 'analyzed')
    else if (filter === 'failed') filtered = videos.filter((v) => v.status === 'failed')
    else if (filter === 'no_subtitle') {
      filtered = videos.filter((v) => v.status === 'analyzed' && !v.has_transcript)
    } else if (filter === 'visual_only') {
      filtered = videos.filter((v) => v.status === 'analyzed' && !v.has_transcript && !v.has_ocr)
    }

    const key = (v: Video): string | number => {
      if (sortColumn === 'title') return v.title
      if (sortColumn === 'segment_count') return v.segment_count ?? 0
      if (sortColumn === 'cost') return v.cost_usd ?? 0
      return v.analyzed_at ?? v.created_at
    }
    const sorted = [...filtered].sort((a, b) => {
      const ka = key(a)
      const kb = key(b)
      if (ka < kb) return sortReverse ? 1 : -1
      if (ka > kb) return sortReverse ? -1 : 1
      return 0
    })
    return sorted
  }, [videos, filter, sortColumn, sortReverse])

  const selected = rows.find((v) => v.id === selectedId) ?? null

  const onSort = (column: SortColumn) => {
    if (column === sortColumn) setSortReverse((r) => !r)
    else {
      setSortColumn(column)
      setSortReverse(false)
    }
  }

  const onSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (query.trim()) navigate(`/search?q=${encodeURIComponent(query.trim())}`)
  }

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="rounded-lg border border-border bg-card p-4">
        <form onSubmit={onSearchSubmit} className="flex gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="描述想尋找的事件、人物、動作或教學內容"
            className="flex-1 rounded border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none"
          />
          <button type="submit" className="rounded bg-primary px-4 py-2 text-sm font-bold text-white">
            搜尋
          </button>
        </form>
      </div>

      <div className="flex min-h-0 flex-1 gap-4">
        <div className="flex w-3/5 flex-col rounded-lg border border-border bg-card p-4">
          <h2 className="mb-3 text-base font-bold">影片庫（{rows.length}）</h2>
          <div className="mb-3 flex gap-2">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                className={`rounded px-3 py-1 text-sm font-bold ${
                  filter === f.key ? 'bg-primary text-white' : 'border border-border text-text-primary'
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            {rows.length === 0 ? (
              <EmptyState
                title={videos && videos.length > 0 ? '這個篩選條件下沒有影片' : '影片庫還沒有任何影片'}
                hints={[videos && videos.length > 0 ? '試試其他篩選' : '先在「影片與分析」頁籤下載並分析影片']}
              />
            ) : (
              <table className="w-full text-left text-sm">
                <thead className="sticky top-0 bg-[#F0F2F5] text-xs text-text-secondary">
                  <tr>
                    <Th label="影片名稱" onClick={() => onSort('title')} active={sortColumn === 'title'} reverse={sortReverse} />
                    <th className="px-2 py-2">長度</th>
                    <Th
                      label="片段數"
                      onClick={() => onSort('segment_count')}
                      active={sortColumn === 'segment_count'}
                      reverse={sortReverse}
                    />
                    <th className="px-2 py-2">分析狀態</th>
                    <Th label="成本" onClick={() => onSort('cost')} active={sortColumn === 'cost'} reverse={sortReverse} />
                    <Th
                      label="分析日期"
                      onClick={() => onSort('analyzed_at')}
                      active={sortColumn === 'analyzed_at'}
                      reverse={sortReverse}
                    />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((v) => (
                    <tr
                      key={v.id}
                      onClick={() => setSelectedId(v.id)}
                      className={`cursor-pointer border-b border-border last:border-0 ${
                        v.id === selectedId ? 'bg-row-selected' : 'hover:bg-app-bg'
                      }`}
                    >
                      <td className="px-2 py-2">{v.title}</td>
                      <td className="px-2 py-2">{formatDuration(v.duration_sec)}</td>
                      <td className="px-2 py-2">{v.segment_count ?? '--'}</td>
                      <td className="px-2 py-2">{STATUS_LABEL[v.status] ?? v.status}</td>
                      <td className="px-2 py-2">{formatCost(v.cost_usd)}</td>
                      <td className="px-2 py-2">{formatDateTime(v.analyzed_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="w-2/5 overflow-auto rounded-lg border border-border bg-card p-4">
          {selected ? (
            <VideoDetailPanel video={selected} onSearchInVideo={(v) => navigate(`/search?video_id=${v.id}&video_title=${encodeURIComponent(v.title)}`)} />
          ) : (
            <EmptyState title="尚未選取影片" />
          )}
        </div>
      </div>
    </div>
  )
}

function Th({
  label,
  onClick,
  active,
  reverse,
}: {
  label: string
  onClick: () => void
  active: boolean
  reverse: boolean
}) {
  return (
    <th className="cursor-pointer select-none px-2 py-2" onClick={onClick}>
      {label}
      {active ? (reverse ? ' ▼' : ' ▲') : ''}
    </th>
  )
}

function VideoDetailPanel({ video, onSearchInVideo }: { video: Video; onSearchInVideo: (video: Video) => void }) {
  const queryClient = useQueryClient()
  const [summaryStatus, setSummaryStatus] = useState('')
  const [reanalysisJobId, setReanalysisJobId] = useState<number | null>(null)
  const [thumbnailFailed, setThumbnailFailed] = useState(false)

  const summaryMutation = useMutation({
    mutationFn: () => regenerateSummary(video.id),
    onSuccess: () => {
      setSummaryStatus('✓ 摘要已更新')
      queryClient.invalidateQueries({ queryKey: ['videos', 'library'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    },
    onError: (err: Error) => setSummaryStatus(`產生摘要失敗：${err.message}`),
  })

  const reanalyzeMutation = useMutation({
    mutationFn: () => reanalyzeVideo(video.id),
    onSuccess: (job) => setReanalysisJobId(job.id),
  })

  const jobQuery = useJobPolling(reanalysisJobId)
  const job = jobQuery.data

  useEffect(() => {
    // 重新分析結束（成功或失敗）要讓列表與統計卡跟著更新；effect 的 deps
    // 只在 job.status 真的變化時觸發，不會在每次 render 都重新 invalidate
    // （直接寫在 render body 裡呼叫 invalidateQueries 是常見的 React
    // 反模式，會導致每次 re-render 都重複觸發）。
    if (job && (job.status === 'completed' || job.status === 'failed')) {
      queryClient.invalidateQueries({ queryKey: ['videos', 'library'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    }
  }, [job, queryClient])

  const busy = summaryMutation.isPending || reanalyzeMutation.isPending || (job ? job.status === 'running' || job.status === 'queued' : false)

  return (
    <div key={video.id} className="flex flex-col gap-3">
      {thumbnailFailed ? (
        <div className="flex h-[180px] w-[320px] items-center justify-center bg-border text-sm text-text-secondary">
          無法產生縮圖
        </div>
      ) : (
        <img
          src={getThumbnailUrl(video.id)}
          alt=""
          className="h-[180px] w-[320px] bg-border object-cover"
          onError={() => setThumbnailFailed(true)}
        />
      )}

      <h3 className="text-base font-bold">{video.title}</h3>
      <p className="text-sm text-text-secondary">
        {formatDuration(video.duration_sec)}
        {video.segment_count !== null ? `｜${video.segment_count} 個片段` : ''}｜分析於 {formatDateTime(video.analyzed_at)}｜
        {formatCost(video.cost_usd)}
      </p>

      <div className="flex gap-2">
        <Badge text={video.has_transcript ? '有字幕' : '無字幕'} kind={video.has_transcript ? 'success' : 'neutral'} />
        <Badge text={video.has_visual ? '有畫面描述' : '無畫面描述'} kind={video.has_visual ? 'success' : 'neutral'} />
        <Badge text={video.has_ocr ? '有 OCR' : '無 OCR'} kind={video.has_ocr ? 'success' : 'neutral'} />
      </div>

      <div>
        <h4 className="mb-2 text-sm font-bold">摘要</h4>
        <p className="text-sm">
          {video.summary ?? (video.status === 'analyzed' ? '尚未產生摘要，按下方「重新產生摘要」產生。' : '這支影片分析失敗，沒有片段可以產生摘要。')}
        </p>
        {summaryStatus && <p className="mt-1 text-sm text-text-secondary">{summaryStatus}</p>}
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          disabled={video.status !== 'analyzed' || busy}
          onClick={() => {
            setSummaryStatus('產生摘要中…')
            summaryMutation.mutate()
          }}
          className="rounded border border-border px-3 py-1.5 text-sm font-bold disabled:opacity-40"
        >
          重新產生摘要
        </button>
        <button
          disabled={video.status !== 'analyzed' || busy}
          onClick={() => onSearchInVideo(video)}
          className="rounded border border-border px-3 py-1.5 text-sm font-bold disabled:opacity-40"
        >
          在此影片內搜尋
        </button>
        <button
          disabled={busy}
          onClick={() => reanalyzeMutation.mutate()}
          className="rounded border border-border px-3 py-1.5 text-sm font-bold disabled:opacity-40"
        >
          重新分析
        </button>
      </div>

      {job && (
        <p className="text-sm text-text-secondary">
          {job.status === 'completed'
            ? '✓ 重新分析完成'
            : job.status === 'failed'
              ? `重新分析失敗：${job.error_message}`
              : `重新分析中…${job.stage ?? ''}`}
        </p>
      )}
    </div>
  )
}
