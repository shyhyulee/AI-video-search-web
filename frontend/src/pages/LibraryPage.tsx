import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowUpDown } from 'lucide-react'
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
import { useLibraryList, type FilterKind, type SortColumn } from '../lib/useLibraryList'
import { useSearchScope } from '../lib/useSearchScope'
import { CATEGORY_ORDER, type VideoCategory } from '../lib/videoCategory'

// 狀態篩選從三顆 chips 改成下拉，是為了把 chips 那一列整條讓給主題分類——
// 半版寬的卡片（§8.10）塞不下「搜尋列＋主題 chips＋狀態 chips」三列控制項，
// 見 docs/11 §8.17.4。
const STATUS_FILTERS: { key: FilterKind; label: string }[] = [
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

// analyzing 也會出現在影片庫：分析成功過的影片按「重新分析」時留在原地跑完，
// 不會跳去「影片分析」再跳回來（見後端 db.list_library_videos()）。
const STATUS_LABEL: Record<string, string> = {
  analyzed: '分析完成',
  failed: '分析失敗',
  analyzing: '重新分析中',
}

/** 「影片庫」頁面，對齊 ui/library_tab.py：篩選／排序列表 + 詳細資訊面板，
 * 見 docs/07-ui-structure-and-features.md 6.2 節。排序改用明確的下拉＋方向切換，
 * 取代原本表格可點擊欄位標題的排序方式（改成 list-item 後不再有欄位標題）。 */
export function LibraryPage() {
  // 清單、篩選、排序、勾選全部住在 useLibraryList；這裡只剩排版與動作。
  const {
    videos, activeJobs, isLoading, isError, refetch,
    rows, selected, categoryOf, statusFiltered, categoryCounts, activeCategory,
    filter, setFilter, setCategory, query, setQuery,
    sortColumn, setSortColumn, sortReverse, toggleSortDirection, select,
    picked, pickedIds, togglePicked, clearPicked,
  } = useLibraryList()
  // 觀看模式：點文件裡的步驟時間戳進去，左播放器、右摘要與文件（見
  // VideoWatchView）。存的是「哪一支影片的第幾秒」，null＝正常的清單版面。
  //
  // 只放在 state、沒有同步到網址：頁籤是 keep-alive 的（見 App.tsx），切走再
  // 切回來狀態還在，所以少了網址只影響「可分享」與「上一頁退出」。要做的話
  // 得處理 keep-alive 下的參數消化，SearchPage 的 `consumedParams` 就是為此
  // 存在的——那是獨立的一步，先不綁進來。
  const [watching, setWatching] = useState<{ videoId: number; sec: number } | null>(null)
  // navigate 只剩「在此／在選取影片內搜尋」在用（設好共用的搜尋範圍後跳到
  // 「片段搜尋」頁）；這頁上方原本那條自由文字搜尋列已移除，搜尋一律在
  // 「片段搜尋」頁進行。
  const navigate = useNavigate()
  const { setScope } = useSearchScope()

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
                onClick={toggleSortDirection}
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
          <div className="md:min-h-0 md:flex-1 md:overflow-auto" aria-busy={isLoading}>
            {isLoading ? (
              <LoadingSkeleton variant="list-item" count={4} />
            ) : isError ? (
              <ErrorState title="載入影片庫失敗" onRetry={() => refetch()} />
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
                  onClick={() => select(v.id)}
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
          {/* 動作列放最底下，跟「影片分析」頁的批次動作列同一個位置。刻意
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
              onClick={clearPicked}
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
      hints: ['先到「新增影片」頁加入影片，再到「影片分析」頁分析'],
    }
  }
  if (query !== '') {
    return {
      title: `找不到符合「${query}」的影片`,
      hints: ['這裡只比對影片的標題與摘要', '要在影片內容裡找片段，請用「片段搜尋」頁'],
    }
  }
  if (category !== 'all') {
    return { title: `「${category}」分類下沒有影片`, hints: ['換一個分類，或選「全部」'] }
  }
  return { title: '這個篩選條件下沒有影片', hints: ['試試其他狀態'] }
}
