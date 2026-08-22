import { formatPercent } from '../lib/format'

interface SimilarityBarProps {
  ratio: number
}

/** 相似度小色條＋百分比文字，避免只用顏色傳達分數，對齊 ui/widgets.py 的 SimilarityBar。 */
export function SimilarityBar({ ratio }: SimilarityBarProps) {
  const clamped = Math.max(0, Math.min(1, ratio))
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-16 overflow-hidden rounded bg-[#E4E7EC]">
        <div className="h-full bg-primary" style={{ width: `${clamped * 100}%` }} />
      </div>
      <span className="text-sm text-text-primary">{formatPercent(ratio)}</span>
    </div>
  )
}
