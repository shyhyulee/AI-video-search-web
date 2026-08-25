import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { MonitorPlay, Search } from 'lucide-react'
import { searchYoutube } from '../api/client'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { LoadingSkeleton } from '../components/LoadingSkeleton'
import { SearchField } from '../components/SearchField'
import { YoutubeResultCard } from '../components/YoutubeResultCard'

const RESULT_LIMIT = 12
/** 對齊後端 youtube_search_service 的 _CACHE_TTL_SEC，避免前端已經過期、
 * 後端還在回快取（或反過來）造成「重新搜尋卻沒有變化」的困惑。 */
const CACHE_TTL_MS = 5 * 60 * 1000

const GRID_CLASS = 'grid grid-cols-1 items-start gap-4 sm:grid-cols-2 lg:grid-cols-3'

/** 「YouTube 搜尋」頁：輸入關鍵字查 YouTube，用卡片列出前 12 筆，點卡片
 * 上的按鈕就地展開網址與說明。這頁只讀 metadata，不下載也不分析影片——
 * 要把影片抓下來分析請到「影片與分析」頁貼網址。 */
export function YoutubeSearchPage() {
  const [input, setInput] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')

  const {
    data,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['youtube-search', submittedQuery],
    queryFn: () => searchYoutube(submittedQuery, RESULT_LIMIT),
    // 只有按下搜尋才查，不邊打字邊打 YouTube。
    enabled: submittedQuery !== '',
    staleTime: CACHE_TTL_MS,
  })

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setSubmittedQuery(input.trim())
  }

  const items = data?.items

  return (
    <div className="flex h-full flex-col gap-4">
      <Card>
        <h2 className="mb-3 text-base font-bold text-text-primary">搜尋 YouTube</h2>
        <form onSubmit={onSubmit} className="flex gap-2">
          <SearchField
            size="lg"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="輸入關鍵字，例如：python 教學"
            aria-label="YouTube 搜尋關鍵字"
          />
          <Button
            type="submit"
            variant="primary"
            size="lg"
            loading={isFetching}
            disabled={input.trim() === ''}
            icon={<Search className="h-4 w-4" aria-hidden="true" />}
          >
            搜尋
          </Button>
        </form>
      </Card>

      <div className="min-h-0 flex-1 overflow-auto" aria-busy={isFetching}>
        {submittedQuery === '' ? (
          <EmptyState
            title="搜尋 YouTube 影片"
            hints={['輸入關鍵字後會列出前 12 筆結果', '點卡片上的「查看詳情」可以看到網址與說明']}
            icon={<MonitorPlay className="h-8 w-8" aria-hidden="true" />}
          />
        ) : isFetching && !items ? (
          <div className={GRID_CLASS}>
            {Array.from({ length: RESULT_LIMIT }).map((_, i) => (
              <LoadingSkeleton key={i} variant="card" />
            ))}
          </div>
        ) : isError ? (
          <ErrorState
            title="YouTube 搜尋失敗"
            detail={error instanceof Error ? error.message : undefined}
            onRetry={() => refetch()}
          />
        ) : !items || items.length === 0 ? (
          <EmptyState title={`找不到「${submittedQuery}」的相關影片`} hints={['換個關鍵字再試一次']} />
        ) : (
          <div className={GRID_CLASS}>
            {items.map((item) => (
              <YoutubeResultCard key={item.video_id} item={item} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
