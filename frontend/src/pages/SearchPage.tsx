import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { exportSearchCsv, getStreamUrl, search } from '../api/client'
import type { SearchResult } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { SimilarityBar } from '../components/SimilarityBar'
import { formatPercent, formatTimeRange, truncate } from '../lib/format'

const SCORE_NA = 'N/A'
const formatScore = (score: number | null) => (score === null ? SCORE_NA : score.toFixed(2))

/** 「搜尋結果」頁面，對齊 ui/search_tab.py：搜尋列、結果列表、詳細分數
 * 面板、HTML5 Video 播放器，見 docs/07-ui-structure-and-features.md 6.3
 * 節與 docs/09-web-ui-migration-plan.md Phase 3「搜尋＋播放器」。 */
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
  const videoRef = useRef<HTMLVideoElement>(null)

  const searchMutation = useMutation({
    mutationFn: (q: string) => search({ query: q, video_id: scopeVideoId }),
    onSuccess: (resp, q) => {
      setResults(resp.results)
      setSelectedIndex(null)
      setStatusText(
        resp.results.length > 0
          ? `找到 ${resp.results.length} 個相關片段｜花費 $${resp.cost_usd.toFixed(4)}`
          : '沒有找到足夠相關的片段，建議使用較簡短的描述、改用人物／動作／物件名稱',
      )
      void q
    },
    onError: (err: Error) => setStatusText(`搜尋失敗：${err.message}`),
  })

  // URL 帶查詢字串進來（例如從影片庫頁面的搜尋列）時自動觸發一次搜尋。
  useEffect(() => {
    const q = searchParams.get('q')
    if (q) {
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
    searchMutation.mutate(queryText.trim())
  }

  const clearScope = () => {
    setScopeVideoId(null)
    setScopeVideoTitle(null)
  }

  const selected = selectedIndex !== null ? results[selectedIndex] : null

  const selectResult = (index: number) => {
    setSelectedIndex(index)
    const result = results[index]
    // 影片來源切換時瀏覽器會重新載入，seek 要等 metadata 讀完才能設定，見
    // <video> 的 onLoadedMetadata。同一支影片內切換片段則可以立刻 seek。
    if (videoRef.current && videoRef.current.dataset.videoId === String(result.video_id)) {
      videoRef.current.currentTime = result.start_sec
      videoRef.current.play().catch(() => {})
    }
  }

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="rounded-lg border border-border bg-card p-4">
        {scopeVideoId !== null && (
          <div className="mb-2 flex items-center gap-2 text-sm text-text-secondary">
            <span>在《{scopeVideoTitle}》中搜尋</span>
            <button onClick={clearScope} className="font-bold text-primary">
              清除範圍，改為全部影片
            </button>
          </div>
        )}
        <form onSubmit={onSubmit} className="flex gap-2">
          <input
            value={queryText}
            onChange={(e) => setQueryText(e.target.value)}
            placeholder="描述想尋找的事件、人物、動作或教學內容"
            className="flex-1 rounded border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none"
          />
          <button type="submit" className="rounded bg-primary px-4 py-2 text-sm font-bold text-white">
            搜尋
          </button>
          <button
            type="button"
            disabled={results.length === 0}
            onClick={() => exportSearchCsv({ query: queryText.trim(), video_id: scopeVideoId })}
            className="rounded border border-border px-4 py-2 text-sm font-bold disabled:opacity-40"
          >
            匯出 CSV
          </button>
        </form>
        <p className="mt-2 text-sm text-text-secondary">{statusText}</p>
      </div>

      <div className="flex min-h-0 flex-1 gap-4">
        <div className="flex w-3/5 flex-col rounded-lg border border-border bg-card p-4">
          <div className="min-h-0 flex-1 overflow-auto">
            {results.length === 0 ? (
              <EmptyState title="輸入描述以搜尋影片內容" hints={['例如：找出工廠中有人出現的片段', '例如：找出全壘打畫面']} />
            ) : (
              <table className="w-full text-left text-sm">
                <thead className="sticky top-0 bg-[#F0F2F5] text-xs text-text-secondary">
                  <tr>
                    <th className="px-2 py-2">排名</th>
                    <th className="px-2 py-2">影片名稱</th>
                    <th className="px-2 py-2">時間範圍</th>
                    <th className="px-2 py-2">相似度</th>
                    <th className="px-2 py-2">融合分數</th>
                    <th className="px-2 py-2">命中來源</th>
                    <th className="px-2 py-2">片段描述</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r, index) => (
                    <tr
                      key={r.segment_id}
                      onClick={() => selectResult(index)}
                      className={`cursor-pointer border-b border-border last:border-0 ${
                        index === selectedIndex ? 'bg-row-selected' : 'hover:bg-app-bg'
                      }`}
                    >
                      <td className="px-2 py-2">{index + 1}</td>
                      <td className="px-2 py-2">{r.video_title}</td>
                      <td className="px-2 py-2">{formatTimeRange(r.start_sec, r.end_sec)}</td>
                      <td className="px-2 py-2">{formatPercent(r.similarity)}</td>
                      <td className="px-2 py-2">{r.fusion_score.toFixed(3)}</td>
                      <td className="px-2 py-2">{r.hit_source}</td>
                      <td className="px-2 py-2">{truncate(r.description, 80)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="flex w-2/5 flex-col gap-3 overflow-auto rounded-lg border border-border bg-card p-4">
          {selected ? (
            <>
              <video
                ref={videoRef}
                key={selected.video_id}
                data-video-id={selected.video_id}
                src={getStreamUrl(selected.video_id)}
                controls
                className="w-full rounded bg-black"
                onLoadedMetadata={(e) => {
                  e.currentTarget.currentTime = selected.start_sec
                  e.currentTarget.play().catch(() => {})
                }}
              />
              <h3 className="text-base font-bold">{selected.video_title}</h3>
              <p className="text-sm text-text-secondary">{formatTimeRange(selected.start_sec, selected.end_sec)}</p>
              <div>
                <span className="text-sm text-text-secondary">最終相似度：</span>
                <SimilarityBar ratio={selected.similarity} />
              </div>
              <p className="text-sm text-text-secondary">字幕分數：{formatScore(selected.transcript_score)}</p>
              <p className="text-sm text-text-secondary">畫面分數：{formatScore(selected.visual_score)}</p>
              <p className="text-sm text-text-secondary">OCR 分數：{formatScore(selected.ocr_score)}</p>
              <p className="text-sm text-text-secondary">融合分數：{selected.fusion_score.toFixed(3)}（排序依據）</p>
              <p className="text-sm text-text-secondary">命中策略：{selected.fusion_strategy}</p>
              <div>
                <h4 className="mb-1 text-sm font-bold">片段描述</h4>
                <p className="text-sm">{selected.description || '（無畫面描述）'}</p>
              </div>
              <div>
                <h4 className="mb-1 text-sm font-bold">字幕內容</h4>
                <p className="text-sm text-text-secondary">{selected.transcript || '（此片段無字幕）'}</p>
              </div>
            </>
          ) : (
            <EmptyState title="尚未選取片段" />
          )}
        </div>
      </div>
    </div>
  )
}
