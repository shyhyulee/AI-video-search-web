import { useQuery } from '@tanstack/react-query'
import { getStats } from '../api/client'
import { formatCost } from '../lib/format'
import { StatCard } from './StatCard'
import { TopNav } from './TopNav'

/** 全域 Header：左側品牌名、中段主導覽（TopNav）、右側精簡統計卡（窄螢幕
 * 漸進隱藏次要項目，避免大型 Stat Card 佔首屏）。
 *
 * 這裡刻意不顯示「當前頁面標題」：TopNav 選中的頁籤已經表明使用者在哪一頁，
 * 再放一次標題是重複資訊，也會跟頁籤搶同一列的水平空間。 */
export function Header() {
  const { data: stats } = useQuery({ queryKey: ['stats'], queryFn: getStats })

  return (
    <header className="flex shrink-0 items-center justify-between gap-4 border-b border-border bg-card px-4 py-3 lg:px-6">
      <h1 className="shrink-0 truncate text-lg font-bold text-text-primary lg:text-xl">AI 影片搜尋</h1>

      <TopNav />

      <div className="flex shrink-0 items-center gap-4 lg:gap-6">
        <StatCard label="待分析" value={stats ? `${stats.pending_count} 支` : '--'} size="compact" />
        <div className="hidden sm:block">
          <StatCard label="已分析" value={stats ? `${stats.analyzed_count} 支` : '--'} size="compact" />
        </div>
        <div className="hidden md:block">
          <StatCard
            label="影片片段"
            value={stats ? stats.segment_count.toLocaleString() : '--'}
            size="compact"
          />
        </div>
        <div className="hidden lg:block">
          <StatCard label="累計成本" value={stats ? formatCost(stats.total_cost_usd) : '--'} size="compact" />
        </div>
      </div>
    </header>
  )
}
