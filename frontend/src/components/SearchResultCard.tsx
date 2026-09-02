import type { KeyboardEvent } from 'react'
import type { SearchResult } from '../api/types'
import { formatTimeRange, truncate } from '../lib/format'

interface SearchResultCardProps {
  result: SearchResult
  rank: number
  selected?: boolean
  onSelect: () => void
}

/** 搜尋結果列，取代 SearchPage／ConversationPage 各自複製貼上的結果表格。
 * 只給標題、時間與描述，不顯示相似度％／融合分數／命中來源（分數留在片段
 * 搜尋頁右側的證據面板）。鍵盤可操作：Tab 可到、Enter／Space 觸發選取。
 *
 * 曾經有一個 `featured` 版型：AI對話頁的第一名結果畫成大張的 Evidence Card、
 * 標「最相關片段」。2026-09-02 依使用者要求拿掉，兩頁的清單改成完全一樣，
 * 那個分支因此沒有呼叫端，一併移除（見 docs/05 §8.24）。 */
export function SearchResultCard({ result, rank, selected = false, onSelect }: SearchResultCardProps) {
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onSelect()
    }
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
