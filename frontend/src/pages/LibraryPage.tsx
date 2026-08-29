import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ArrowUpDown } from 'lucide-react'
import {
  generateVideoDocument,
  getVideoDocument,
  listActiveJobs,
  listVideos,
  reanalyzeVideo,
} from '../api/client'
import type { Job, Video } from '../api/types'
import { Badge } from '../components/Badge'
import { Button, IconButton } from '../components/Button'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { FilterChip } from '../components/FilterChip'
import { LoadingSkeleton } from '../components/LoadingSkeleton'
import { SearchField } from '../components/SearchField'
import { VideoDocumentView } from '../components/VideoDocumentView'
import { VideoListItem } from '../components/VideoListItem'
import { formatCost, formatDateTime, formatDuration } from '../lib/format'
import { useJobPolling } from '../lib/useJobPolling'
import { useSearchScope } from '../lib/useSearchScope'
import { CATEGORY_ORDER, classifyVideo, matchesLibraryQuery, type VideoCategory } from '../lib/videoCategory'

// 篩選只留分析狀態。原本還有「無字幕」（`!has_transcript`）與「純畫面」
// （`!has_transcript && !has_ocr`）兩個模態篩選，已移除，見 docs/11 §8.7。
type FilterKind = 'all' | 'analyzed' | 'failed'
type SortColumn = 'title' | 'segment_count' | 'cost' | 'analyzed_at'

// 狀態篩選從三顆 chips 改成下拉，是為了把 chips 那一列整條讓給主題分類——
// 半版寬的卡片（§8.10）塞不下「搜尋列＋主題 chips＋狀態 chips」三列控制項，
// 見 docs/11 §8.17.4。
const STATUS_FILTERS: { key: FilterKind; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'analyzed', label: '分析完成' },
  { key: 'failed', label: '分析失敗' },
]

/** 重新分析進行中時，清單與 job 狀態的重取間隔。跟「影片與分析」頁同一個
 * 節奏——那頁的說明見 VideosPage 的 LIST_POLL_MS。 */
const LIBRARY_POLL_MS = 3000

const SORT_LABEL: Record<SortColumn, string> = {
  title: '影片名稱',
  segment_count: '片段數',
  cost: '成本',
  analyzed_at: '分析日期',
}

// analyzing 也會出現在影片庫：分析成功過的影片按「重新分析」時留在原地跑完，
// 不會跳去「影片與分析」再跳回來（見後端 db.list_library_videos()）。
const STATUS_LABEL: Record<string, string> = {
  analyzed: '分析完成',
  failed: '分析失敗',
  analyzing: '重新分析中',
}

/** 「影片庫」頁面，對齊 ui/library_tab.py：篩選／排序列表 + 詳細資訊面板，
 * 見 docs/07-ui-structure-and-features.md 6.2 節。排序改用明確的下拉＋方向切換，
 * 取代原本表格可點擊欄位標題的排序方式（改成 list-item 後不再有欄位標題）。 */
export function LibraryPage() {
  const [filter, setFilter] = useState<FilterKind>('all')
  const [category, setCategory] = useState<VideoCategory | 'all'>('all')
  // 庫內搜尋：邊打邊篩，不用送出。它跟「搜尋影片」頁的語意檢索是兩件事——
  // 只比對已經在手上的標題與摘要，不打 API、不跳頁，見 docs/11 §8.17.5。
  const [query, setQuery] = useState('')
  const [sortColumn, setSortColumn] = useState<SortColumn>('analyzed_at')
  const [sortReverse, setSortReverse] = useState(true)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  // 勾選成搜尋範圍的影片。用 Set 而不是陣列，跟「影片與分析」頁的批次勾選
  // 一致（見 VideosPage 的 toggleSelected）。刻意不設數量上限——VideosPage
  // 的上限是分析成本天花板，搜尋範圍沒有這個成本（查詢向量只 embed 一次）。
  const [picked, setPicked] = useState<Set<number>>(new Set())
  // navigate 只剩「在此／在選取影片內搜尋」在用（設好共用的搜尋範圍後跳到
  // 「搜尋影片」頁）；這頁上方原本那條自由文字搜尋列已移除，搜尋一律在
  // 「搜尋影片」頁進行。
  const navigate = useNavigate()
  const { setScope } = useSearchScope()

  const {
    data: videos,
    isLoading: videosLoading,
    isError: videosError,
    refetch: refetchVideos,
  } = useQuery({
    queryKey: ['videos', 'library'],
    queryFn: () => listVideos(),
    // 有影片在重新分析時清單要跟著重取：`status` 什麼時候變回 analyzed、片段數
    // 與成本什麼時候換成新一輪的，只有清單知道，job 輪詢看不到。
    refetchInterval: (query) =>
      query.state.data?.some((v) => v.status === 'analyzing') ? LIBRARY_POLL_MS : false,
  })

  // 重新分析的進度來源。跟「影片與分析」頁共用同一個 query key，兩頁只會有
  // 一份快取、一組請求；重新整理後也是靠它把進行中的工作接回來。
  const { data: activeJobs } = useQuery({
    queryKey: ['jobs', 'active', 'analysis'],
    queryFn: () => listActiveJobs('analysis'),
    refetchInterval: LIBRARY_POLL_MS,
  })

  // 每支影片的主題分類。純函式，videos 沒換就不必重算。
  const categoryOf = useMemo(() => {
    const map = new Map<number, VideoCategory>()
    for (const v of videos ?? []) map.set(v.id, classifyVideo(v))
    return map
  }, [videos])

  // 狀態篩選單獨抽出來，因為 chips 上的數量要跟著它變（但不跟著關鍵字變，
  // 理由見 categoryCounts）。
  const statusFiltered = useMemo(() => {
    if (!videos) return []
    // 「分析完成」也收 analyzing：重新分析中的影片手上還有上一輪的結果，
    // 用這個篩選找它是找得到的，不該因為正在更新就整支消失。
    if (filter === 'analyzed') return videos.filter((v) => v.status !== 'failed')
    if (filter === 'failed') return videos.filter((v) => v.status === 'failed')
    return videos
  }, [videos, filter])

  // chips 上的數量只受狀態篩選影響，**刻意不受搜尋關鍵字影響**：跟著關鍵字變的
  // 話，打字時每一顆數字都在跳，那排數字就失去「這個分類有幾支影片」的意義。
  const categoryCounts = useMemo(() => {
    const counts = new Map<VideoCategory, number>()
    for (const v of statusFiltered) {
      const c = categoryOf.get(v.id)
      if (c) counts.set(c, (counts.get(c) ?? 0) + 1)
    }
    return counts
  }, [statusFiltered, categoryOf])

  // 選中的分類可能在換了狀態篩選之後整個消失（例如只看「分析失敗」時一支運動
  // 賽事都沒有）。跟 §8.7 的預設選取一樣用推導、不用 useEffect 同步 state：直接
  // 當成「全部」，就不會出現「選中一顆畫面上不存在的 chip、清單卻是空的」。
  const activeCategory = category !== 'all' && !categoryCounts.has(category) ? 'all' : category

  const rows = useMemo(() => {
    const filtered = statusFiltered.filter(
      (v) =>
        (activeCategory === 'all' || categoryOf.get(v.id) === activeCategory) && matchesLibraryQuery(v, query),
    )

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
  }, [statusFiltered, activeCategory, categoryOf, query, sortColumn, sortReverse])

  // 預設選第一支影片，右側詳細面板不會是空白。刻意用「推導」而不是 useEffect
  // 去同步 selectedId：這樣切換篩選／排序後如果原本選的那支不在清單裡了，會
  // 自動落回第一筆，不需要額外的 effect，也不會出現「面板空白一瞬間」。
  const selected = rows.find((v) => v.id === selectedId) ?? rows[0] ?? null

  // 勾選中的影片可能已經被刪掉（或還原成待分析）。跟 selectedId／activeCategory
  // 一樣用推導、不用 useEffect 同步：畫面永遠只會算進「現在還存在而且可搜」的
  // 那幾支，不會送出一個指向不存在影片的搜尋範圍。刻意用整份 videos 而不是
  // 篩選後的 rows——切換分類或打關鍵字時不該把已經勾好的影片踢出範圍。
  const pickedIds = useMemo(
    () => (videos ?? []).filter((v) => picked.has(v.id) && v.status === 'analyzed').map((v) => v.id),
    [videos, picked],
  )

  const togglePicked = (id: number) =>
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const searchInVideos = (ids: number[]) => {
    setScope(ids)
    navigate('/search')
  }

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex flex-col gap-4 md:min-h-0 md:flex-1 md:flex-row">
        {/* 主從版面一律左右各半（md:w-1/2），跟搜尋影片／對話搜尋同一個比例，
            切換頁籤時分隔線不會左右跳動。改比例要三頁一起改。 */}
        <Card className="flex w-full min-w-0 flex-col md:min-h-0 md:w-1/2">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-base font-bold text-text-primary">影片庫（{rows.length}）</h2>
            <div className="flex items-center gap-2">
              <label className="text-xs text-text-secondary" htmlFor="library-status">
                狀態
              </label>
              <select
                id="library-status"
                value={filter}
                onChange={(e) => setFilter(e.target.value as FilterKind)}
                className="h-9 rounded-xl border border-border bg-card px-2 text-sm text-text-primary focus:border-primary focus:outline-none"
              >
                {STATUS_FILTERS.map((f) => (
                  <option key={f.key} value={f.key}>
                    {f.label}
                  </option>
                ))}
              </select>
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
          {/* 外面包一層普通 div：SearchField 的容器帶 `flex-1`，直接放進這張
              flex-column 卡片會被拉高去填滿剩餘高度。包起來之後 flex-1 沒有
              flex 父層可作用，輸入框就維持自己的高度。 */}
          <div className="mb-2">
            <SearchField
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜尋影片庫的標題或摘要…"
              aria-label="搜尋影片庫"
            />
          </div>

          {/* 主題 chips：只列出庫裡真的有影片的分類（跟 YouTube 一樣是動態的），
              順序由 CATEGORY_ORDER 決定，見 docs/11 §8.17.4。 */}
          <div className="mb-2 flex gap-2 overflow-x-auto pb-1">
            <FilterChip
              label="全部"
              count={statusFiltered.length}
              active={activeCategory === 'all'}
              onClick={() => setCategory('all')}
            />
            {CATEGORY_ORDER.filter((c) => categoryCounts.has(c)).map((c) => (
              <FilterChip
                key={c}
                label={c}
                count={categoryCounts.get(c)}
                active={activeCategory === c}
                onClick={() => setCategory(c)}
              />
            ))}
          </div>
          <div className="md:min-h-0 md:flex-1 md:overflow-auto" aria-busy={videosLoading}>
            {videosLoading ? (
              <LoadingSkeleton variant="list-item" count={4} />
            ) : videosError ? (
              <ErrorState title="載入影片庫失敗" onRetry={() => refetchVideos()} />
            ) : rows.length === 0 ? (
              <EmptyState
                {...emptyStateText({
                  libraryEmpty: !videos || videos.length === 0,
                  query: query.trim(),
                  category: activeCategory,
                })}
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
                  // 勾選＝加入搜尋範圍，跟「點這一列看詳細」是兩種語意，靠
                  // VideoListItem 的 stopPropagation 並存在同一列上。只有分析
                  // 完成的影片有片段可搜，其餘停用而不是整個藏起來，使用者才
                  // 知道「不是漏掉了，是還不能選」。
                  checked={picked.has(v.id)}
                  onCheckedChange={() => togglePicked(v.id)}
                  checkboxDisabled={v.status !== 'analyzed'}
                  checkboxDisabledReason="這支影片還沒有分析完成的片段，不能加入搜尋範圍"
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
          {/* 動作列放最底下，跟「影片與分析」頁的批次動作列同一個位置。刻意
              不往上加第四列控制項——左欄上方已經有「標題＋狀態／排序」「庫內
              搜尋」「主題 chips」三列，半版寬（§8.10）再加就塞爆了。 */}
          <div className="mt-2 flex flex-wrap gap-2 border-t border-border pt-2">
            <Button
              variant="primary"
              size="sm"
              disabled={pickedIds.length === 0}
              onClick={() => searchInVideos(pickedIds)}
            >
              在選取影片內搜尋
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={picked.size === 0}
              onClick={() => setPicked(new Set())}
            >
              清除選取
            </Button>
            <p className="self-center text-sm text-text-secondary" aria-live="polite">
              已選 {pickedIds.length} 支
            </p>
          </div>
        </Card>

        {/* overflow-hidden 而不是 overflow-auto：詳細面板自己排成固定高度的
            flex column，只有最下面的摘要在真的太長時才內部捲動，整張卡片不捲。 */}
        <Card className="w-full min-w-0 md:min-h-0 md:w-1/2 md:overflow-hidden">
          {selected ? (
            // key 讓換一支影片時整個面板重新掛載。沒有它的話 React 會沿用同一個
            // 元件實例，`reanalysisJobId`／`summaryStatus` 會留在上面——切到另一支
            // 影片時，會把前一支的重新分析進度顯示在新選的影片身上。
            <VideoDetailPanel
              key={selected.id}
              video={selected}
              category={categoryOf.get(selected.id)}
              activeJob={activeJobs?.find((j) => j.video_id === selected.id)}
              onSearchInVideo={(v) => searchInVideos([v.id])}
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

/** 空清單的四種成因要講不同的話，否則使用者分不出是關鍵字沒中、這個分類沒東西，
 * 還是整個影片庫本來就是空的。 */
function emptyStateText({
  libraryEmpty,
  query,
  category,
}: {
  libraryEmpty: boolean
  /** 已經 trim 過的搜尋關鍵字。 */
  query: string
  category: VideoCategory | 'all'
}): { title: string; hints: string[] } {
  if (libraryEmpty) {
    return {
      title: '影片庫還沒有任何影片',
      hints: ['先到「YouTube 搜尋」頁加入影片，再到「影片與分析」頁分析'],
    }
  }
  if (query !== '') {
    return {
      title: `找不到符合「${query}」的影片`,
      hints: ['這裡只比對影片的標題與摘要', '要在影片內容裡找片段，請用「搜尋影片」頁'],
    }
  }
  if (category !== 'all') {
    return { title: `「${category}」分類下沒有影片`, hints: ['換一個分類，或選「全部」'] }
  }
  return { title: '這個篩選條件下沒有影片', hints: ['試試其他狀態'] }
}

function VideoDetailPanel({
  video,
  category,
  activeJob,
  onSearchInVideo,
}: {
  video: Video
  /** 由 `classifyVideo()` 從標題與摘要推導，不是資料庫欄位，見 lib/videoCategory.ts。 */
  category: VideoCategory | undefined
  /** 後端回報的、這支影片進行中的分析工作。重新整理後靠它把進度接回來——
   * `reanalysisJobId` 只活在 React state，F5 就沒了。 */
  activeJob: Job | undefined
  onSearchInVideo: (video: Video) => void
}) {
  const queryClient = useQueryClient()
  const [documentStatus, setDocumentStatus] = useState('')
  const [reanalysisJobId, setReanalysisJobId] = useState<number | null>(null)

  // `video.document_type` 是清單就有的輕量旗標，用它當 enabled 條件：沒整理過
  // 的影片完全不會打這支 API（後端那時會回 404，那是正常狀態不是錯誤，不該讓
  // react-query 一直重試）。
  const documentQuery = useQuery({
    queryKey: ['video-document', video.id],
    queryFn: () => getVideoDocument(video.id),
    enabled: video.document_type !== null,
    staleTime: Infinity, // 文件只有按下「整理成文件」才會變，不用自動重取
  })

  const documentMutation = useMutation({
    mutationFn: () => generateVideoDocument(video.id),
    onSuccess: (resp) => {
      setDocumentStatus('✓ 文件與摘要已更新')
      // 直接把結果塞進快取，省掉一次來回。清單一定要 invalidate——摘要也是這
      // 一次呼叫產出的（見後端 video_service.generate_document），上方那段
      // 摘要讀的是清單裡的 video.summary，不重取就不會跟著換。
      queryClient.setQueryData(['video-document', video.id], resp)
      queryClient.invalidateQueries({ queryKey: ['videos', 'library'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    },
    onError: (err: Error) => setDocumentStatus(`整理失敗：${err.message}`),
  })

  const reanalyzeMutation = useMutation({
    mutationFn: () => reanalyzeVideo(video.id),
    onSuccess: (job) => {
      setReanalysisJobId(job.id)
      queryClient.invalidateQueries({ queryKey: ['videos', 'library'] })
    },
  })

  useEffect(() => {
    // 把後端撈回來的進行中工作接上輪詢。接上之後就交給 useJobPolling——
    // job 到終態會離開 activeJob，但 reanalysisJobId 留著，才顯示得出結果。
    // oxlint-disable-next-line react/set-state-in-effect
    if (activeJob && activeJob.id !== reanalysisJobId) setReanalysisJobId(activeJob.id)
  }, [activeJob, reanalysisJobId])

  const jobQuery = useJobPolling(reanalysisJobId)
  const job = jobQuery.data

  // 每個 job 只收尾一次。這道去重不是效能微調——沒有它的話，effect 每次被
  // 重跑都會再 invalidate 一輪，對後端連發 /videos 與 /stats。
  const settledJobIds = useRef<Set<number>>(new Set())
  useEffect(() => {
    // 重新分析結束（成功或失敗）要讓列表與統計卡跟著更新。
    //
    // 這裡刻意不跳 toast。原本會跳「重新分析完成」，結果是無限迴圈：
    // `toast` 來自 ToastContext，跳一則通知會讓 ToastProvider 重繪、context
    // value 換成新物件，effect 的 deps 就變了、再跑一次、再跳一則……畫面被同
    // 一則訊息疊滿。ToastProvider 的 value 已經改成 useMemo 穩定住（見
    // components/Toast.tsx），但這則通知本身也不需要——影片跑完會自己從
    // 「分析中」變回「分析完成」，畫面上看得出來。
    if (!job || (job.status !== 'completed' && job.status !== 'failed')) return
    if (settledJobIds.current.has(job.id)) return
    settledJobIds.current.add(job.id)
    queryClient.invalidateQueries({ queryKey: ['videos', 'library'] })
    queryClient.invalidateQueries({ queryKey: ['stats'] })
  }, [job, queryClient])

  // 影片自己的 status 也算 busy：重新整理後 job 還沒接回來的那幾秒，按鈕
  // 不能是可按的——後端會回 409，而且摘要／搜尋這時看到的是上一輪的結果。
  const analyzing = video.status === 'analyzing' || job?.status === 'running' || job?.status === 'queued'
  const busy = documentMutation.isPending || reanalyzeMutation.isPending || analyzing

  return (
    <div className="flex flex-col gap-3 md:h-full">
      {/* 這裡原本有一張滿版縮圖。移除的理由：它是純裝飾（面板裡沒有播放器，
          點了不會播），卻吃掉 md:max-h-[42vh] 的高度——而一份 SOP 有二三十個
          步驟，最缺的就是垂直空間。清單列的小縮圖（VideoListItem）還在，辨識
          影片靠那裡就夠了。 */}
      <div className="shrink-0">
        {/* flex-wrap：標題長的時候讓分類標籤換到下一行，不要把標題擠成一長串省略號。 */}
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-base font-bold text-text-primary">{video.title}</h3>
          {category && <Badge text={category} kind="primary" />}
        </div>
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
        {/* 原本這裡有「重新產生摘要」與「整理成文件」兩顆。摘要那顆移除了——
            文件的 overview 一稿兩用，整理文件時會一起更新摘要（見後端
            video_service.generate_document），兩顆按鈕產出高度重疊的文字沒有
            意義。後端的 POST /videos/{id}/summary 端點還在，只是前端不再呼叫，
            照 uploadVideo() 的先例。 */}
        <Button
          variant="secondary"
          size="sm"
          disabled={video.status !== 'analyzed' || busy}
          onClick={() => {
            setDocumentStatus('整理中…會一併更新摘要，影片越長越久，請稍候')
            documentMutation.mutate()
          }}
        >
          {video.document_type ? '重新整理文件' : '整理成文件'}
        </Button>
        <Button variant="secondary" size="sm" disabled={busy} onClick={() => reanalyzeMutation.mutate()}>
          重新分析
        </Button>
      </div>

      {/* analyzing 也要顯示，不能只看 job：重新整理之後 job 還沒接回來，
          但影片的 status 已經說得很清楚。階段文字優先用 job 的（比較即時），
          沒有就退回 videos.pipeline_stage（analyzer 每個階段都會寫進 DB）。 */}
      {(job || analyzing) && (
        <p className="shrink-0 text-sm text-text-secondary" aria-live="polite">
          {job?.status === 'completed'
            ? '✓ 重新分析完成'
            : job?.status === 'failed'
              ? `重新分析失敗：${job.error_message}`
              : `重新分析中…${job?.stage ?? video.pipeline_stage ?? ''}`}
        </p>
      )}

      {/* 內容區放在最下面：長度不固定（幾行到二三十個步驟都有可能），擺在中間
          會把按鈕推到不固定的位置，換一支影片按鈕就跳一次。放最後之後，上面的
          標題／標籤／按鈕在每支影片都固定在同樣的高度。
          它同時是整個面板唯一會捲動的地方——上面全是 shrink-0，這裡吃掉剩下的
          高度（md:flex-1），真的塞不下才在自己內部捲，卡片本身不捲。

          摘要與文件原本是兩個頁籤，已合併成上下一段：兩者來自同一次 LLM 呼叫
          （文件的 overview 就是摘要），分成兩個頁籤等於要使用者自己去對照兩段
          講同一件事的文字。摘要固定在最上面，位置不隨有沒有文件而變。 */}
      <div className="md:min-h-0 md:flex-1 md:overflow-auto">
        <h4 className="mb-1 text-sm font-bold text-text-primary">摘要</h4>
        <p className="text-sm leading-relaxed text-text-primary">
          {video.summary ??
            (video.status === 'analyzed'
              ? '尚未產生摘要，按上方「整理成文件」會一併產生。'
              : '這支影片分析失敗，沒有片段可以產生摘要。')}
        </p>

        <div className="mt-4 border-t border-border pt-4">
          {documentMutation.isPending || documentQuery.isLoading ? (
            <LoadingSkeleton variant="list-item" count={3} />
          ) : documentQuery.data ? (
            <VideoDocumentView document={documentQuery.data.document} />
          ) : (
            <p className="text-sm leading-relaxed text-text-secondary">
              {video.status === 'analyzed'
                ? '尚未整理成文件。按上方「整理成文件」，系統會依影片內容判斷要產生流程 SOP、教學步驟、課堂筆記，還是內容紀錄，並同時更新上方的摘要。'
                : '這支影片分析失敗，沒有片段可以整理成文件。'}
            </p>
          )}
          {documentStatus && (
            <p className="mt-2 text-sm text-text-secondary" aria-live="polite">
              {documentStatus}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
