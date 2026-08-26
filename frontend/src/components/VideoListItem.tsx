import type { KeyboardEvent, ReactNode } from 'react'
import type { Video } from '../api/types'
import { VideoPoster } from './VideoPoster'

interface VideoListItemProps {
  video: Video
  selected?: boolean
  checked?: boolean
  onCheckedChange?: (checked: boolean) => void
  /** 勾選框不可用（例如已達批次上限）。已勾選的項目不該被停用，否則會變成
   * 取消不掉——呼叫端負責只對「還沒勾選」的項目傳 true。 */
  checkboxDisabled?: boolean
  /** 勾選框停用的原因，顯示成 tooltip。 */
  checkboxDisabledReason?: string
  onClick?: () => void
  meta: ReactNode
  trailing?: ReactNode
}

/** 影片清單列：縮圖＋標題＋可插槽 meta／trailing，取代密集表格列；
 * 列與列之間用 border 分隔，不做每列一張卡片。可點擊時是鍵盤可操作的
 * button 語意（Tab 可到、Enter／Space 觸發），並有可見 focus ring。 */
export function VideoListItem({
  video,
  selected = false,
  checked,
  onCheckedChange,
  checkboxDisabled = false,
  checkboxDisabledReason,
  onClick,
  meta,
  trailing,
}: VideoListItemProps) {
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!onClick) return
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onClick()
    }
  }

  return (
    <div
      onClick={onClick}
      onKeyDown={onKeyDown}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      className={`flex items-center gap-3 border-b border-l-4 border-border py-2.5 pl-2 pr-1 last:border-b-0 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary ${
        onClick ? 'cursor-pointer' : ''
      } ${selected ? 'border-l-primary bg-primary-soft' : 'border-l-transparent hover:bg-sand'}`}
    >
      {onCheckedChange && (
        <input
          type="checkbox"
          checked={checked ?? false}
          disabled={checkboxDisabled}
          title={checkboxDisabled ? checkboxDisabledReason : undefined}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => onCheckedChange(e.target.checked)}
          className="h-4 w-4 shrink-0 accent-primary disabled:cursor-not-allowed disabled:opacity-40"
          aria-label={`選取 ${video.title}`}
        />
      )}
      <VideoPoster videoId={video.id} size="sm" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-bold text-text-primary">{video.title}</p>
        <div className="truncate text-xs text-text-secondary">{meta}</div>
      </div>
      {trailing && <div className="shrink-0">{trailing}</div>}
    </div>
  )
}
