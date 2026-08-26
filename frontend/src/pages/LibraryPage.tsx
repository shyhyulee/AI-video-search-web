import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ArrowUpDown } from 'lucide-react'
import { listVideos, reanalyzeVideo, regenerateSummary } from '../api/client'
import type { Video } from '../api/types'
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

// 篩選只留分析狀態。原本還有「無字幕」（`!has_transcript`）與「純畫面」
// （`!has_transcript && !has_ocr`）兩個模態篩選，已移除，見 docs/11 §8.7。
type FilterKind = 'all' | 'analyzed' | 'failed'
type SortColumn = 'title' | 'segment_count' | 'cost' | 'analyzed_at'

const FILTERS: { key: FilterKind; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'analyzed', label: '分析完成' },
  { key: 'failed', label: '分析失敗' },
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

  // 預設選第一支影片，右側詳細面板不會是空白。刻意用「推導」而不是 useEffect
  // 去同步 selectedId：這樣切換篩選／排序後如果原本選的那支不在清單裡了，會
  // 自動落回第一筆，不需要額外的 effect，也不會出現「面板空白一瞬間」。
  const selected = rows.find((v) => v.id === selectedId) ?? rows[0] ?? null

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex flex-col gap-4 md:min-h-0 md:flex-1 md:flex-row">
        {/* 主從版面一律左右各半（md:w-1/2），跟搜尋影片／對話搜尋同一個比例，
            切換頁籤時分隔線不會左右跳動。改比例要三頁一起改。 */}
        <Card className="flex w-full min-w-0 flex-col md:min-h-0 md:w-1/2">
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
                hints={[
                  videos && videos.length > 0
                    ? '試試其他篩選'
                    : '先到「YouTube 搜尋」頁加入影片，再到「影片與分析」頁分析',
                ]}
              />
            ) : (
              rows.map((v) => (
                <VideoListItem
                  key={v.id}
                  video={v}
                  // 比對 selected?.id 而不是 selectedId：預設選中的第一筆
                  // 還沒被點過，selectedId 仍是 null，用它會讓清單沒有任何
                  // 一列反白、跟右側面板顯示的內容對不上。
                  selected={v.id === selected?.id}
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

        {/* overflow-hidden 而不是 overflow-auto：詳細面板自己排成固定高度的
            flex column，只有最下面的摘要在真的太長時才內部捲動，整張卡片不捲。 */}
        <Card className="w-full min-w-0 md:min-h-0 md:w-1/2 md:overflow-hidden">
          {selected ? (
            <VideoDetailPanel
              video={selected}
              onSearchInVideo={(v) => navigate(`/search?video_id=${v.id}&video_title=${encodeURIComponent(v.title)}`)}
            />
          ) : (
            // 清單有東西時一定會有選取（預設第一筆），所以這個空狀態只在
            // 清單本身是空的時候才會出現。
            <EmptyState title="沒有可顯示的影片" />
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
    <div key={video.id} className="flex flex-col gap-3 md:h-full">
      {/* 縮圖回到滿版寬度（並排版把它壓到只剩約 256px，太小），改用 max-h 綁住
          高度來換取「面板不捲動」：`aspect-video w-full` 決定寬度與比例，
          `md:max-h-[34vh]` 在矮螢幕自動把它壓回來、`object-cover` 負責裁切。
          高度跟著視窗長，摘要下方原本剩下的空白就被縮圖吃掉了。
          ≤900px 不套 max-h——手機版面本來就整頁捲動，不需要限制。 */}
      <VideoPoster videoId={video.id} size="fill" className="shrink-0 md:max-h-[42vh]" />

      <div className="shrink-0">
        <h3 className="text-base font-bold text-text-primary">{video.title}</h3>
        <p className="mt-1 text-sm text-text-secondary">
          {formatDuration(video.duration_sec)}
          {video.segment_count !== null ? `｜${video.segment_count} 個片段` : ''}
          ｜分析於 {formatDateTime(video.analyzed_at)}｜{formatCost(video.cost_usd)}
        </p>
      </div>

      <div className="flex shrink-0 flex-wrap gap-2">
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
        <p className="shrink-0 text-sm text-text-secondary" aria-live="polite">
          {job.status === 'completed'
            ? '✓ 重新分析完成'
            : job.status === 'failed'
              ? `重新分析失敗：${job.error_message}`
              : `重新分析中…${job.stage ?? ''}`}
        </p>
      )}

      {/* 摘要放在最下面：長度不固定（幾行到一整段都有可能），擺在中間會把
          按鈕推到不固定的位置，換一支影片按鈕就跳一次。放最後之後，上面的
          縮圖／標題／標籤／按鈕在每支影片都固定在同樣的高度。
          它同時是整個面板唯一會捲動的地方——上面全是 shrink-0，摘要吃掉剩下的
          高度（md:flex-1），真的塞不下才在自己內部捲，卡片本身不捲。 */}
      <div className="md:min-h-0 md:flex-1 md:overflow-auto">
        <h4 className="mb-2 text-sm font-bold text-text-primary">摘要</h4>
        <p className="text-sm leading-relaxed text-text-primary">
          {video.summary ??
            (video.status === 'analyzed' ? '尚未產生摘要，按上方「重新產生摘要」產生。' : '這支影片分析失敗，沒有片段可以產生摘要。')}
        </p>
        {summaryStatus && (
          <p className="mt-1 text-sm text-text-secondary" aria-live="polite">
            {summaryStatus}
          </p>
        )}
      </div>
    </div>
  )
}
