import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { exportSearchCsv, search } from '../api/client'
import type { SearchResult } from '../api/types'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { EvidencePanel } from '../components/EvidencePanel'
import { SearchField } from '../components/SearchField'
import { SearchResultCard } from '../components/SearchResultCard'
import { VideoPlayer } from '../components/VideoPlayer'

/** 「搜尋影片」頁面（頁籤原名「搜尋結果」，改名以反映它是**執行**搜尋的地方
 * 而不只是看結果的地方），對齊 ui/search_tab.py：搜尋列、結果列表、詳細分數
 * 面板、HTML5 Video 播放器，見 docs/07-ui-structure-and-features.md 6.3
 * 節與 docs/10-web-ui-ux-warm-responsive-design.md §6.3。
 *
 * 全站**只有這一頁能輸入自由文字搜尋**：影片庫頁上方原本也有一條搜尋列，會
 * 帶著 `?q=` 跳過來，已移除（見 docs/11 §8.6）。影片庫剩下的入口是「在此影片
 * 內搜尋」，帶 `?video_id=` 過來設定搜尋範圍、不帶查詢字串。 */
export function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [queryText, setQueryText] = useState('')
  const [scopeVideoId, setScopeVideoId] = useState<number | null>(null)
  const [scopeVideoTitle, setScopeVideoTitle] = useState<string | null>(null)
  const [results, setResults] = useState<SearchResult[]>([])
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  // 這次的選取是使用者點的（true，點了就想看）還是搜完自動帶出來的預設
  // （false，只顯示不播）。
  const [playOnSelect, setPlayOnSelect] = useState(false)
  const [statusText, setStatusText] = useState('描述想尋找的事件、人物、動作或教學內容')
  const searchStartedAt = useRef(0)

  // 搜尋範圍隨參數一起帶進 mutate，不從 closure 讀 state：從影片庫「只搜這支
  // 影片」進來時 setScopeVideoId 還沒生效，靠 closure 會搜成全部影片。
  const searchMutation = useMutation({
    mutationFn: ({ q, videoId }: { q: string; videoId: number | null }) => search({ query: q, video_id: videoId }),
    onSuccess: (resp) => {
      setResults(resp.results)
      // 搜完自動選第一名，右側直接帶出播放器與證據面板，不用再手動點一下；
      // 沒有結果才回到 null，讓右側顯示「沒有找到片段」的提示。
      setSelectedIndex(resp.results.length > 0 ? 0 : null)
      setPlayOnSelect(false)
      const elapsedSec = ((Date.now() - searchStartedAt.current) / 1000).toFixed(1)
      setStatusText(
        resp.results.length > 0
          ? `找到 ${resp.results.length} 個相關片段｜耗時 ${elapsedSec} 秒｜花費 $${resp.cost_usd.toFixed(4)}`
          : `沒有找到足夠相關的片段（耗時 ${elapsedSec} 秒），建議使用較簡短的描述、改用人物／動作／物件名稱`,
      )
    },
    onError: (err: Error) => setStatusText(`搜尋失敗：${err.message}`),
  })

  // 影片庫頁會用 /search?q=… 或 /search?video_id=…&video_title=… 帶條件過來。
  // 這頁在頁籤之間切換時不會卸載（見 App.tsx 的 KeepAlivePage），所以不能只在
  // mount 時看一次 URL，每次參數變化都要處理，否則從影片庫點第二次就沒反應。
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

    const videoIdParam = searchParams.get('video_id')
    const nextScopeId = videoIdParam !== null ? Number(videoIdParam) : scopeVideoId
    if (videoIdParam !== null) {
      setScopeVideoId(nextScopeId)
      setScopeVideoTitle(searchParams.get('video_title'))
    }

    const q = searchParams.get('q')
    if (q) {
      setQueryText(q)
      setStatusText('搜尋中…')
      searchStartedAt.current = Date.now()
      searchMutation.mutate({ q, videoId: nextScopeId })
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
    searchMutation.mutate({ q: queryText.trim(), videoId: scopeVideoId })
  }

  const clearScope = () => {
    setScopeVideoId(null)
    setScopeVideoTitle(null)
  }

  const selected = selectedIndex !== null ? results[selectedIndex] : null

  return (
    <div className="flex h-full flex-col gap-4">
      <Card>
        {scopeVideoId !== null && (
          <div className="mb-2 flex items-center gap-2 text-sm text-text-secondary">
            <span>目前作用中的篩選：只在《{scopeVideoTitle}》中搜尋</span>
            <button onClick={clearScope} className="font-bold text-primary-hover">
              清除範圍，改為全部影片
            </button>
          </div>
        )}
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
          <Button
            type="button"
            variant="secondary"
            disabled={results.length === 0}
            onClick={() => exportSearchCsv({ query: queryText.trim(), video_id: scopeVideoId })}
          >
            匯出 CSV
          </Button>
        </form>
        <p className="mt-2 text-sm text-text-secondary" aria-live="polite">
          {statusText}
        </p>
      </Card>

      <div className="flex flex-col gap-4 md:min-h-0 md:flex-1 md:flex-row">
        {/* 主從版面一律左右各半（md:w-1/2）：影片庫／搜尋影片／對話搜尋三頁
            共用同一個比例，切換頁籤時分隔線不會左右跳動。改比例要三頁一起改。 */}
        <Card className="flex w-full min-w-0 flex-col md:min-h-0 md:w-1/2">
          <div className="md:min-h-0 md:flex-1 md:overflow-auto">
            {results.length === 0 ? (
              <EmptyState title="輸入描述以搜尋影片內容" hints={['例如：找出工廠中有人出現的片段', '例如：找出全壘打畫面']} />
            ) : (
              results.map((r, index) => (
                <SearchResultCard
                  key={r.segment_id}
                  result={r}
                  rank={index + 1}
                  selected={index === selectedIndex}
                  onSelect={() => {
                    setSelectedIndex(index)
                    setPlayOnSelect(true)
                  }}
                />
              ))
            )}
          </div>
        </Card>

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
    </div>
  )
}
