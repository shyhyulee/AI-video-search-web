import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ArrowUpDown } from 'lucide-react'
import { listActiveJobs, listVideos } from '../api/client'
import type { Video } from '../api/types'
import { Button, IconButton } from '../components/Button'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { FilterChip } from '../components/FilterChip'
import { LoadingSkeleton } from '../components/LoadingSkeleton'
import { SearchField } from '../components/SearchField'
import { VideoDetailPanel } from '../components/VideoDetailPanel'
import { VideoWatchView } from '../components/VideoWatchView'
import { VideoListItem } from '../components/VideoListItem'
import { formatCost, formatDateTime, formatDuration } from '../lib/format'
import { activeJobsKey, libraryVideosKey } from '../lib/queryKeys'
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
  // 觀看模式：點文件裡的步驟時間戳進去，左播放器、右摘要與文件（見
  // VideoWatchView）。存的是「哪一支影片的第幾秒」，null＝正常的清單版面。
  //
  // 只放在 state、沒有同步到網址：頁籤是 keep-alive 的（見 App.tsx），切走再
  // 切回來狀態還在，所以少了網址只影響「可分享」與「上一頁退出」。要做的話
  // 得處理 keep-alive 下的參數消化，SearchPage 的 `consumedParams` 就是為此
  // 存在的——那是獨立的一步，先不綁進來。
  const [watching, setWatching] = useState<{ videoId: number; sec: number } | null>(null)
  const navigate = useNavigate()
  const { setScope } = useSearchScope()

  const {
    data: videos,
    isLoading: videosLoading,
    isError: videosError,
    refetch: refetchVideos,
  } = useQuery({
    queryKey: libraryVideosKey(),
    queryFn: () => listVideos(),
    // 有影片在重新分析時清單要跟著重取：`status` 什麼時候變回 analyzed、片段數
    // 與成本什麼時候換成新一輪的，只有清單知道，job 輪詢看不到。
    refetchInterval: (query) =>
      query.state.data?.some((v) => v.status === 'analyzing') ? LIBRARY_POLL_MS : false,
  })

  // 重新分析的進度來源。跟「影片與分析」頁共用同一個 query key，兩頁只會有
  // 一份快取、一組請求；重新整理後也是靠它把進行中的工作接回來。
  const { data: activeJobs } = useQuery({
    queryKey: activeJobsKey('analysis'),
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

  // 觀看中的影片可能已經被刪掉或還原成待分析（清單每 3 秒重取）；查不到就退回
  // 清單，不要留在一個指向不存在影片的播放畫面。
  const watchedVideo = watching ? (videos ?? []).find((v) => v.id === watching.videoId) : undefined
  if (watching && watchedVideo) {
    return (
      <VideoWatchView
        // key 讓換一支影片時整個重新掛載，播放器不會沿用上一支的狀態
        key={watchedVideo.id}
        video={watchedVideo}
        category={categoryOf.get(watchedVideo.id)}
        startSec={watching.sec}
        onBack={() => setWatching(null)}
      />
    )
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
              onWatchAt={(sec) => setWatching({ videoId: selected.id, sec })}
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
