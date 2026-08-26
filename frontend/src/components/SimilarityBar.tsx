import { formatPercent } from '../lib/format'

interface SimilarityBarProps {
  /** null＝這個模態沒有內容可比（例如整段無字幕），顯示空條與 N/A。 */
  ratio: number | null
}

/** 相似度小色條＋百分比文字，避免只用顏色傳達分數。 */
export function SimilarityBar({ ratio }: SimilarityBarProps) {
  const clamped = ratio === null ? 0 : Math.max(0, Math.min(1, ratio))
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-16 overflow-hidden rounded-full bg-sand">
        <div className="h-full bg-primary" style={{ width: `${clamped * 100}%` }} />
      </div>
      <span className={`shrink-0 text-sm ${ratio === null ? 'text-text-muted' : 'text-text-primary'}`}>
        {ratio === null ? 'N/A' : formatPercent(clamped)}
      </span>
    </div>
  )
}
