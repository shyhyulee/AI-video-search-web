import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listActiveJobs, listVideos } from '../api/client'
import type { Video } from '../api/types'
import { activeJobsKey, libraryVideosKey } from './queryKeys'
import { useSearchScope } from './useSearchScope'
import { classifyVideo, matchesLibraryQuery, type VideoCategory } from './videoCategory'

/** 「影片庫」頁的資料層：清單本身、跑在它上面的重新分析工作，以及使用者在左欄
 * 操作出來的那一份檢視（狀態篩選 → 主題分類 → 關鍵字 → 排序）。
 *
 * 抽出來的理由跟 `useAnalysisQueue` 一樣（docs/refactor-board.html F3）：頁面檔
 * 裡有六個 memo 在算清單、兩個 query 在拉資料，而畫面本身只是把 `rows` 攤開來
 * 排版。混在一起時，「改一下排序」跟「改一下卡片長相」動的是同一個 411 行的檔案。
 *
 * **四個推導刻意不用 `useEffect` 同步 state**（維持重構前的寫法，不是這次新增的
 * 選擇）：`activeCategory`、`selected`、`pickedIds` 都是從現有資料算出來的，用
 * effect 去追會多一次 render、而且中間那一幀是不一致的狀態。
 */

// 篩選只留分析狀態。原本還有「無字幕」（`!has_transcript`）與「純畫面」
// （`!has_transcript && !has_ocr`）兩個模態篩選，已移除，見 docs/05 §8.7。
export type FilterKind = 'all' | 'analyzed' | 'failed'
export type SortColumn = 'title' | 'segment_count' | 'cost' | 'analyzed_at'

/** 重新分析進行中時，清單與 job 狀態的重取間隔。跟「影片分析」頁同一個
 * 節奏——那頁的說明見 VideosPage 的 LIST_POLL_MS。 */
const LIBRARY_POLL_MS = 3000

export function useLibraryList() {
  const [filter, setFilter] = useState<FilterKind>('all')
  const [category, setCategory] = useState<VideoCategory | 'all'>('all')
  // 庫內搜尋：邊打邊篩，不用送出。它跟「片段搜尋」頁的語意檢索是兩件事——
  // 只比對已經在手上的標題與摘要，不打 API、不跳頁，見 docs/05 §8.17.5。
  const [query, setQuery] = useState('')
  const [sortColumn, setSortColumn] = useState<SortColumn>('analyzed_at')
  const [sortReverse, setSortReverse] = useState(true)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  // **勾選就是搜尋範圍本身**，這頁不另外存一份。以前是本地的 `Set<number>`，
  // 只有按下「在選取影片內搜尋」時才灌進共用範圍——於是「在片段搜尋頁清除範圍」
  // 或「移掉一個 chip」都不會反映回這裡的 checkbox，切回影片庫還勾著（頁籤是
  // keep-alive）。同一件事兩份狀態、單向同步，遲早分岔，見 docs/05 §8.25。
  //
  // 代價講明白：勾選當下範圍就生效，不再有「先勾好、按了才算」的暫存語意。
  // 刻意不設數量上限——VideosPage 的上限是分析成本天花板，搜尋範圍沒有這個
  // 成本（查詢向量只 embed 一次）。
  const { videoIds: scopeVideoIds, setScope, clearScope } = useSearchScope()
  const picked = useMemo(() => new Set(scopeVideoIds), [scopeVideoIds])

  const {
    data: videos,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: libraryVideosKey(),
    queryFn: () => listVideos(),
    // 有影片在重新分析時清單要跟著重取：`status` 什麼時候變回 analyzed、片段數
    // 與成本什麼時候換成新一輪的，只有清單知道，job 輪詢看不到。
    refetchInterval: (query) =>
      query.state.data?.some((v) => v.status === 'analyzing') ? LIBRARY_POLL_MS : false,
  })

  // 重新分析的進度來源。跟「影片分析」頁共用同一個 query key，兩頁只會有
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
    setScope(picked.has(id) ? scopeVideoIds.filter((v) => v !== id) : [...scopeVideoIds, id])

  return {
    // 原始資料與載入狀態
    videos,
    activeJobs,
    isLoading,
    isError,
    refetch,
    // 使用者操作出來的檢視
    rows,
    selected,
    categoryOf,
    statusFiltered,
    categoryCounts,
    activeCategory,
    // 控制項
    filter,
    setFilter,
    setCategory,
    query,
    setQuery,
    sortColumn,
    setSortColumn,
    sortReverse,
    toggleSortDirection: () => setSortReverse((r) => !r),
    select: setSelectedId,
    // 搜尋範圍的勾選
    picked,
    pickedIds,
    togglePicked,
    clearPicked: clearScope,
  }
}
