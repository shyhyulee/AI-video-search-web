import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ArrowUpDown } from 'lucide-react'
import { listVideos, reanalyzeVideo, regenerateSummary } from '../api/client'
import type { Video } from '../api/types'
import { Badge } from '../components/Badge'
import { Button, IconButton } from '../components/Button'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { FilterChip } from '../components/FilterChip'
import { LoadingSkeleton } from '../components/LoadingSkeleton'
import { VideoListItem } from '../components/VideoListItem'
import { VideoPoster } from '../components/VideoPoster'
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

const SORT_LABEL: Record<SortColumn, string> = {
  title: '影片名稱',
  segment_count: '片段數',
  cost: '成本',
  analyzed_at: '分析日期',
}

const STATUS_LABEL: Record<string, string> = { analyzed: '分析完成', failed: '分析失敗' }

/** 「影片庫」頁面，對齊 ui/library_tab.py：篩選／排序列表 + 詳細資訊面板，
 * 見 docs/07-ui-structure-and-features.md 6.2 節。排序改用明確的下拉＋方向切換，
 * 取代原本表格可點擊欄位標題的排序方式（改成 list-item 後不再有欄位標題）。 */
export function LibraryPage() {
  const [filter, setFilter] = useState<FilterKind>('all')
  const [sortColumn, setSortColumn] = useState<SortColumn>('analyzed_at')
  const [sortReverse, setSortReverse] = useState(true)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  // navigate 只剩「在此影片內搜尋」在用（帶 video_id 範圍跳到「搜尋影片」頁）；
  // 這頁上方原本那條自由文字搜尋列已移除，搜尋一律在「搜尋影片」頁進行。
  const navigate = useNavigate()

  const {
    data: videos,
    isLoading: videosLoading,
    isError: videosError,
    refetch: refetchVideos,
  } = useQuery({ queryKey: ['videos', 'library'], queryFn: () => listVideos() })

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

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex flex-col gap-4 md:min-h-0 md:flex-1 md:flex-row">
        <Card className="flex w-full flex-col md:min-h-0 md:w-3/5">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-base font-bold text-text-primary">影片庫（{rows.length}）</h2>
            <div className="flex items-center gap-2">
              <label className="text-xs text-text-secondary" htmlFor="library-sort">
                排序
              </label>
              <select
                id="library-sort"
                value={sortColumn}
                onChange={(e) => setSortColumn(e.target.value as SortColumn)}
                className="h-9 rounded-xl border border-border bg-card px-2 text-sm text-text-primary focus:border-primary focus:outline-none"
              >
                {(Object.keys(SORT_LABEL) as SortColumn[]).map((col) => (
                  <option key={col} value={col}>
                    {SORT_LABEL[col]}
                  </option>
                ))}
              </select>
              <IconButton
                icon={<ArrowUpDown className="h-4 w-4" />}
                aria-label={sortReverse ? '目前為遞減排序，點擊改為遞增' : '目前為遞增排序，點擊改為遞減'}
                onClick={() => setSortReverse((r) => !r)}
              />
            </div>
          </div>
          <div className="mb-2 flex gap-2 overflow-x-auto pb-1">
            {FILTERS.map((f) => (
              <FilterChip key={f.key} label={f.label} active={filter === f.key} onClick={() => setFilter(f.key)} />
            ))}
          </div>
          <div className="md:min-h-0 md:flex-1 md:overflow-auto" aria-busy={videosLoading}>
            {videosLoading ? (
              <LoadingSkeleton variant="list-item" count={4} />
            ) : videosError ? (
              <ErrorState title="載入影片庫失敗" onRetry={() => refetchVideos()} />
            ) : rows.length === 0 ? (
              <EmptyState
                title={videos && videos.length > 0 ? '這個篩選條件下沒有影片' : '影片庫還沒有任何影片'}
                hints={[videos && videos.length > 0 ? '試試其他篩選' : '先在「影片與分析」頁籤下載並分析影片']}
              />
            ) : (
              rows.map((v) => (
                <VideoListItem
                  key={v.id}
                  video={v}
                  selected={v.id === selectedId}
                  onClick={() => setSelectedId(v.id)}
                  meta={
                    <>
                      {formatDuration(v.duration_sec)} ・{' '}
                      {v.segment_count !== null ? `${v.segment_count} 個片段` : '--'} ・{' '}
                      {STATUS_LABEL[v.status] ?? v.status}
                    </>
                  }
                  trailing={
                    <div className="text-right">
                      <p className="text-sm font-bold text-text-primary">{formatCost(v.cost_usd)}</p>
                      <p className="text-xs text-text-muted">{formatDateTime(v.analyzed_at)}</p>
                    </div>
                  }
                />
              ))
            )}
          </div>
        </Card>

        <Card className="w-full md:min-h-0 md:w-2/5 md:overflow-auto">
          {selected ? (
            <VideoDetailPanel
              video={selected}
              onSearchInVideo={(v) => navigate(`/search?video_id=${v.id}&video_title=${encodeURIComponent(v.title)}`)}
            />
          ) : (
            <EmptyState title="尚未選取影片" />
          )}
        </Card>
      </div>
    </div>
  )
}

function VideoDetailPanel({ video, onSearchInVideo }: { video: Video; onSearchInVideo: (video: Video) => void }) {
  const queryClient = useQueryClient()
  const [summaryStatus, setSummaryStatus] = useState('')
  const [reanalysisJobId, setReanalysisJobId] = useState<number | null>(null)

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
    // 只在 job.status 真的變化時觸發，不會在每次 render 都重新 invalidate。
    if (job && (job.status === 'completed' || job.status === 'failed')) {
      queryClient.invalidateQueries({ queryKey: ['videos', 'library'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    }
  }, [job, queryClient])

  const busy =
    summaryMutation.isPending || reanalyzeMutation.isPending || (job ? job.status === 'running' || job.status === 'queued' : false)

  return (
    <div key={video.id} className="flex flex-col gap-3">
      <VideoPoster videoId={video.id} size="lg" />

      <h3 className="text-base font-bold text-text-primary">{video.title}</h3>
      <p className="text-sm text-text-secondary">
        {formatDuration(video.duration_sec)}
        {video.segment_count !== null ? `｜${video.segment_count} 個片段` : ''}｜分析於 {formatDateTime(video.analyzed_at)}｜
        {formatCost(video.cost_usd)}
      </p>

      <div className="flex flex-wrap gap-2">
        <Badge text={video.has_transcript ? '有字幕' : '無字幕'} kind={video.has_transcript ? 'success' : 'neutral'} />
        <Badge text={video.has_visual ? '有畫面描述' : '無畫面描述'} kind={video.has_visual ? 'success' : 'neutral'} />
        <Badge text={video.has_ocr ? '有 OCR' : '無 OCR'} kind={video.has_ocr ? 'success' : 'neutral'} />
      </div>

      <div>
        <h4 className="mb-2 text-sm font-bold text-text-primary">摘要</h4>
        <p className="text-sm leading-relaxed text-text-primary">
          {video.summary ??
            (video.status === 'analyzed' ? '尚未產生摘要，按下方「重新產生摘要」產生。' : '這支影片分析失敗，沒有片段可以產生摘要。')}
        </p>
        {summaryStatus && (
          <p className="mt-1 text-sm text-text-secondary" aria-live="polite">
            {summaryStatus}
          </p>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <Button variant="primary" size="sm" disabled={video.status !== 'analyzed' || busy} onClick={() => onSearchInVideo(video)}>
          在此影片內搜尋
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={video.status !== 'analyzed' || busy}
          onClick={() => {
            setSummaryStatus('產生摘要中…')
            summaryMutation.mutate()
          }}
        >
          重新產生摘要
        </Button>
        <Button variant="secondary" size="sm" disabled={busy} onClick={() => reanalyzeMutation.mutate()}>
          重新分析
        </Button>
      </div>

      {job && (
        <p className="text-sm text-text-secondary" aria-live="polite">
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
