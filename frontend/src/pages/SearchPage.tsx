import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { search } from '../api/client'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { EvidencePanel } from '../components/EvidencePanel'
import { SearchField } from '../components/SearchField'
import { SearchResultCard } from '../components/SearchResultCard'
import { SearchScopeBar } from '../components/SearchScopeBar'
import { VideoPlayer } from '../components/VideoPlayer'
import { useResultSelection } from '../lib/useResultSelection'
import { useSearchScope } from '../lib/useSearchScope'

/** 「片段搜尋」頁面（頁籤原名「搜尋結果」，改名以反映它是**執行**搜尋的地方
 * 而不只是看結果的地方），對齊 ui/search_tab.py：搜尋列、結果列表、詳細分數
 * 面板、HTML5 Video 播放器，見 docs/archive/07-ui-structure-and-features.md 6.3
 * 節與 docs/prompts/10-web-ui-ux-warm-responsive-design.md §6.3。
 *
 * 全站**只有這一頁能輸入自由文字搜尋**：影片庫頁上方原本也有一條搜尋列，會
 * 帶著 `?q=` 跳過來，已移除（見 docs/05 §8.6）。影片庫剩下的入口是「在此影片
 * 內搜尋」／「在選取影片內搜尋」，它們改用共用的 useSearchScope() 設定範圍再
 * 導過來，不再用 `?video_id=` 帶參數——範圍現在也要給「AI對話」頁用，兩頁
 * 各自從 URL 解析會分岔。 */
export function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [queryText, setQueryText] = useState('')
  const { videoIds: scopeVideoIds } = useSearchScope()
  // 結果、選中哪一筆、播不播——跟 AI對話 頁共用同一份規則，見 lib/useResultSelection.ts。
  const { results, selectedIndex, playOnSelect, selected, showResults, pick } = useResultSelection()
  const [statusText, setStatusText] = useState('描述想尋找的事件、人物、動作或教學內容')
  const searchStartedAt = useRef(0)

  // 搜尋範圍隨參數一起帶進 mutate，不從 closure 讀：從影片庫設定範圍再導過來
  // 時，這次 render 的 context 值可能還是舊的，靠 closure 會搜錯範圍。
  // 空陣列要送 null 而不是 []：後端的 [] 是「限定了範圍但一支都沒選」，會回零筆。
  const searchMutation = useMutation({
    mutationFn: ({ q, videoIds }: { q: string; videoIds: number[] }) =>
      search({ query: q, video_ids: videoIds.length > 0 ? videoIds : null }),
    onSuccess: (resp) => {
      // 搜完自動選第一名、但不播；沒有結果就回到未選取，讓右側顯示「沒有找到
      // 片段」的提示。
      showResults(resp.results)
      const elapsedSec = ((Date.now() - searchStartedAt.current) / 1000).toFixed(1)
      setStatusText(
        resp.results.length > 0
          ? `找到 ${resp.results.length} 個相關片段｜耗時 ${elapsedSec} 秒｜花費 $${resp.cost_usd.toFixed(4)}`
          : `沒有找到足夠相關的片段（耗時 ${elapsedSec} 秒），建議使用較簡短的描述、改用人物／動作／物件名稱`,
      )
    },
    onError: (err: Error) => setStatusText(`搜尋失敗：${err.message}`),
  })

  // 還有 /search?q=… 這條路徑（目前沒有頁面在用，保留給外部連結／書籤）。
  // 搜尋範圍已經改走 useSearchScope()，不再從 URL 解析。
  // 這頁在頁籤之間切換時不會卸載（見 App.tsx 的 KeepAlivePage），所以不能只在
  // mount 時看一次 URL，每次參數變化都要處理，否則帶第二次就沒反應。
  // 消化完把參數清掉，並記下剛處理過的字串，避免 setSearchParams 自己造成的
  // 那次變化又被當成新請求。
  const consumedParams = useRef('')
  useEffect(() => {
    const raw = searchParams.toString()
    if (raw === '') {
      // 參數已清空，解除封鎖：下次即使帶一模一樣的關鍵字進來也會重新搜尋。
      consumedParams.current = ''
      return
    }
    if (raw === consumedParams.current) return
    consumedParams.current = raw

    const q = searchParams.get('q')
    if (q) {
      setQueryText(q)
      setStatusText('搜尋中…')
      searchStartedAt.current = Date.now()
      searchMutation.mutate({ q, videoIds: scopeVideoIds })
    }
    setSearchParams({}, { replace: true })
    // searchMutation 每次 render 都是新物件，放進 deps 會讓 effect 每輪都跑；
    // 真正的觸發條件只有 URL 參數變化。
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!queryText.trim()) {
      setStatusText('請輸入想搜尋的內容')
      return
    }
    setStatusText('搜尋中…')
    searchStartedAt.current = Date.now()
    searchMutation.mutate({ q: queryText.trim(), videoIds: scopeVideoIds })
  }

  // 搜尋框跟結果清單疊在**左半邊**、寬度一樣；右半邊的播放器與證據面板因此
  // 從最上緣開始，不必等搜尋框那一塊的高度。三頁共用的左右各半（md:w-1/2）
  // 比例沒有變，變的是搜尋框從「橫跨整頁的第一列」收進左欄。
  return (
    <div className="flex h-full flex-col gap-4 md:min-h-0 md:flex-row">
      <div className="flex w-full min-w-0 flex-col gap-4 md:min-h-0 md:w-1/2">
        <Card className="shrink-0">
          {/* 改變範圍不會自動重新搜尋（跟改關鍵字一樣要按一次「搜尋」），維持
              「按下去才會花錢」的可預期行為。 */}
          <SearchScopeBar className="mb-2" />
          <form onSubmit={onSubmit} className="flex items-center gap-2">
            <SearchField
              size="lg"
              value={queryText}
              onChange={(e) => setQueryText(e.target.value)}
              placeholder="描述想尋找的事件、人物、動作或教學內容"
            />
            <Button type="submit" variant="primary" size="lg">
              搜尋
            </Button>
          </form>
          <p className="mt-2 text-sm text-text-secondary" aria-live="polite">
            {statusText}
          </p>
        </Card>

        <Card className="flex min-w-0 flex-col md:min-h-0 md:flex-1">
          <div className="md:min-h-0 md:flex-1 md:overflow-auto">
            {results.length === 0 ? (
              <EmptyState title="輸入描述以搜尋影片內容" hints={['例如：找出工廠中有人出現的片段', '例如：找出工廠中有機器人出現的片段']} />
            ) : (
              results.map((r, index) => (
                <SearchResultCard
                  key={r.segment_id}
                  result={r}
                  rank={index + 1}
                  selected={index === selectedIndex}
                  onSelect={() => pick(index)}
                />
              ))
            )}
          </div>
        </Card>
      </div>

      <Card className="flex w-full min-w-0 flex-col gap-3 md:min-h-0 md:w-1/2 md:overflow-auto">
        {/* 有結果就一定有選取（搜完自動選第一名），所以這裡的空狀態只剩兩種
            情況：還沒搜過，或搜過但沒找到。兩者要給不一樣的提示——「尚未選取
            片段」在自動選取之後已經不可能是真的。 */}
        {selected ? (
          <>
            <VideoPlayer
              videoId={selected.video_id}
              startSec={selected.start_sec}
              title={selected.video_title}
              autoPlay={playOnSelect}
            />
            <EvidencePanel result={selected} />
          </>
        ) : searchMutation.isSuccess ? (
          <EmptyState
            title="沒有找到相關片段"
            hints={['試試較簡短的描述', '改用人物／動作／物件名稱', '或清除搜尋範圍改搜全部影片']}
          />
        ) : (
          <EmptyState title="搜尋後這裡會顯示片段與播放器" />
        )}
      </Card>
    </div>
  )
}
