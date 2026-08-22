import { useQuery } from '@tanstack/react-query'
import { getStats } from '../api/client'
import { formatCost } from '../lib/format'
import { StatCard } from './StatCard'

/** 全域 Header：左側標題副標，右側四張精簡指標卡，對齊 ui/header.py。 */
export function Header() {
  const { data: stats } = useQuery({ queryKey: ['stats'], queryFn: getStats })

  return (
    <header className="flex items-center justify-between border-b border-border bg-card px-6 py-4">
      <div>
        <h1 className="text-xl font-bold text-text-primary">AI 影片搜尋</h1>
        <p className="mt-1 text-sm text-text-secondary">快速找到影片中的關鍵時刻</p>
      </div>
      <div className="flex gap-6">
        <StatCard label="待分析" value={stats ? `${stats.pending_count} 支` : '--'} />
        <StatCard label="已分析" value={stats ? `${stats.analyzed_count} 支` : '--'} />
        <StatCard label="影片片段" value={stats ? stats.segment_count.toLocaleString() : '--'} />
        <StatCard label="累計成本" value={stats ? formatCost(stats.total_cost_usd) : '--'} />
      </div>
    </header>
  )
}
