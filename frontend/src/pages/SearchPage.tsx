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

/** 「搜尋結果」頁面，對齊 ui/search_tab.py：搜尋列、結果列表、詳細分數
 * 面板、HTML5 Video 播放器，見 docs/07-ui-structure-and-features.md 6.3
 * 節與 docs/10-web-ui-ux-warm-responsive-design.md §6.3。 */
export function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [queryText, setQueryText] = useState(searchParams.get('q') ?? '')
  const [scopeVideoId, setScopeVideoId] = useState<number | null>(
    searchParams.has('video_id') ? Number(searchParams.get('video_id')) : null,
  )
  const [scopeVideoTitle, setScopeVideoTitle] = useState<string | null>(searchParams.get('video_title'))
  const [results, setResults] = useState<SearchResult[]>([])
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  const [statusText, setStatusText] = useState('描述想尋找的事件、人物、動作或教學內容')
  const searchStartedAt = useRef(0)

  const searchMutation = useMutation({
    mutationFn: (q: string) => search({ query: q, video_id: scopeVideoId }),
    onSuccess: (resp) => {
      setResults(resp.results)
      setSelectedIndex(null)
      const elapsedSec = ((Date.now() - searchStartedAt.current) / 1000).toFixed(1)
      setStatusText(
        resp.results.length > 0
          ? `找到 ${resp.results.length} 個相關片段｜耗時 ${elapsedSec} 秒｜花費 $${resp.cost_usd.toFixed(4)}`
          : `沒有找到足夠相關的片段（耗時 ${elapsedSec} 秒），建議使用較簡短的描述、改用人物／動作／物件名稱`,
      )
    },
    onError: (err: Error) => setStatusText(`搜尋失敗：${err.message}`),
  })

  // URL 帶查詢字串進來（例如從影片庫頁面的搜尋列）時自動觸發一次搜尋。
  useEffect(() => {
    const q = searchParams.get('q')
    if (q) {
      searchStartedAt.current = Date.now()
      searchMutation.mutate(q)
      setSearchParams((prev) => {
        prev.delete('q')
        return prev
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 只在掛載時看一次 URL，之後的搜尋改由使用者操作觸發
  }, [])

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!queryText.trim()) {
      setStatusText('請輸入想搜尋的內容')
      return
    }
    setStatusText('搜尋中…')
    searchStartedAt.current = Date.now()
    searchMutation.mutate(queryText.trim())
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
            <button onClick={clearScope} className="font-bold text-primary">
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
        <p className="mt-2 text-sm text-text-secondary">{statusText}</p>
      </Card>

      <div className="flex min-h-0 flex-1 gap-4">
        <Card className="flex w-3/5 flex-col">
          <div className="min-h-0 flex-1 overflow-auto">
            {results.length === 0 ? (
              <EmptyState title="輸入描述以搜尋影片內容" hints={['例如：找出工廠中有人出現的片段', '例如：找出全壘打畫面']} />
            ) : (
              results.map((r, index) => (
                <SearchResultCard
                  key={r.segment_id}
                  result={r}
                  rank={index + 1}
                  selected={index === selectedIndex}
                  onSelect={() => setSelectedIndex(index)}
                />
              ))
            )}
          </div>
        </Card>

        <Card className="flex w-2/5 flex-col gap-3 overflow-auto">
          {selected ? (
            <>
              <VideoPlayer videoId={selected.video_id} startSec={selected.start_sec} title={selected.video_title} />
              <EvidencePanel result={selected} />
            </>
          ) : (
            <EmptyState title="尚未選取片段" />
          )}
        </Card>
      </div>
    </div>
  )
}
