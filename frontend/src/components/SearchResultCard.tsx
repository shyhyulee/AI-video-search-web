import type { KeyboardEvent } from 'react'
import type { SearchResult } from '../api/types'
import { formatTimeRange, truncate } from '../lib/format'

interface SearchResultCardProps {
  result: SearchResult
  rank: number
  selected?: boolean
  featured?: boolean
  onSelect: () => void
}

/** 搜尋結果列，取代 SearchPage／ConversationPage 各自複製貼上的結果表格。
 * featured＝對話搜尋第一名結果的大版型 Evidence Card，其餘（含 Search 頁
 * 全部結果）用緊湊列表版型，兩者都只給標題、時間與描述，不顯示相似度％／
 * 融合分數／命中來源（分數留在搜尋影片頁右側的證據面板）。鍵盤可操作：
 * Tab 可到、Enter／Space 觸發選取。 */
export function SearchResultCard({ result, rank, selected = false, featured = false, onSelect }: SearchResultCardProps) {
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onSelect()
    }
  }

  if (featured) {
    return (
      <div
        onClick={onSelect}
        onKeyDown={onKeyDown}
        role="button"
        tabIndex={0}
        className={`cursor-pointer rounded-card border p-3 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary ${
          selected ? 'border-primary bg-primary-soft' : 'border-border bg-card hover:border-primary'
        }`}
      >
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="text-xs font-bold text-primary-hover">最相關片段</span>
          <span className="shrink-0 text-xs text-text-muted">{formatTimeRange(result.start_sec, result.end_sec)}</span>
        </div>
        <p className="mb-2 truncate text-sm font-bold text-text-primary">{result.video_title}</p>
        <p className="text-sm leading-relaxed text-text-secondary">{result.description || '（無畫面描述）'}</p>
      </div>
    )
  }

  return (
    <div
      onClick={onSelect}
      onKeyDown={onKeyDown}
      role="button"
      tabIndex={0}
      className={`flex cursor-pointer items-center gap-3 border-b border-border px-2 py-2 text-sm last:border-0 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary ${
        selected ? 'bg-row-selected' : 'hover:bg-sand'
      }`}
    >
      <span className="w-6 shrink-0 text-text-secondary">{rank}</span>
      <div className="min-w-0 flex-[2]">
        <p className="truncate font-bold text-text-primary">{result.video_title}</p>
        <p className="text-xs text-text-secondary">{formatTimeRange(result.start_sec, result.end_sec)}</p>
      </div>
      <p className="min-w-0 flex-[3] truncate text-text-secondary">{truncate(result.description, 80)}</p>
    </div>
  )
}
