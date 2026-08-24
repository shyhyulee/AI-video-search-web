import type { SearchResult } from '../api/types'
import { formatPercent, formatTimeRange, truncate } from '../lib/format'
import { SimilarityBar } from './SimilarityBar'

interface SearchResultCardProps {
  result: SearchResult
  rank: number
  selected?: boolean
  featured?: boolean
  onSelect: () => void
}

/** 搜尋結果列，取代 SearchPage／ConversationPage 各自複製貼上的結果表格。
 * featured＝對話搜尋第一名結果的大版型 Evidence Card，其餘（含 Search 頁
 * 全部結果）用緊湊列表版型。 */
export function SearchResultCard({ result, rank, selected = false, featured = false, onSelect }: SearchResultCardProps) {
  if (featured) {
    return (
      <div
        onClick={onSelect}
        className={`cursor-pointer rounded-card border p-3 transition-colors ${
          selected ? 'border-primary bg-primary-soft' : 'border-border bg-card hover:border-primary'
        }`}
      >
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="text-xs font-bold text-primary">最相關片段</span>
          <span className="shrink-0 text-xs text-text-muted">{formatTimeRange(result.start_sec, result.end_sec)}</span>
        </div>
        <p className="mb-2 truncate text-sm font-bold text-text-primary">{result.video_title}</p>
        <SimilarityBar ratio={result.similarity} />
        <p className="mt-2 text-sm leading-relaxed text-text-secondary">{result.description || '（無畫面描述）'}</p>
        <p className="mt-2 text-xs text-text-muted">命中來源：{result.hit_source}</p>
      </div>
    )
  }

  return (
    <div
      onClick={onSelect}
      className={`flex cursor-pointer items-center gap-3 border-b border-border px-2 py-2 text-sm last:border-0 ${
        selected ? 'bg-row-selected' : 'hover:bg-sand'
      }`}
    >
      <span className="w-6 shrink-0 text-text-secondary">{rank}</span>
      <div className="min-w-0 flex-[2]">
        <p className="truncate font-bold text-text-primary">{result.video_title}</p>
        <p className="text-xs text-text-secondary">{formatTimeRange(result.start_sec, result.end_sec)}</p>
      </div>
      <span className="w-12 shrink-0 text-text-primary">{formatPercent(result.similarity)}</span>
      <span className="w-16 shrink-0 text-text-secondary">{result.fusion_score.toFixed(3)}</span>
      <span className="w-16 shrink-0 truncate text-text-secondary">{result.hit_source}</span>
      <p className="min-w-0 flex-[3] truncate text-text-secondary">{truncate(result.description, 80)}</p>
    </div>
  )
}
