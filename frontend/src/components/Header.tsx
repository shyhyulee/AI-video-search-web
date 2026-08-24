import { useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getStats } from '../api/client'
import { formatCost } from '../lib/format'
import { StatCard } from './StatCard'

const PAGE_TITLE: Record<string, string> = {
  '/videos': '影片與分析',
  '/library': '影片庫',
  '/search': '搜尋結果',
  '/conversation': '對話搜尋',
}

/** 全域 Header：左側品牌名＋當前頁面標題，右側精簡統計卡（窄螢幕漸進隱藏次要項目，
 * 避免大型 Stat Card 佔首屏）。 */
export function Header() {
  const { data: stats } = useQuery({ queryKey: ['stats'], queryFn: getStats })
  const location = useLocation()
  const pageTitle = PAGE_TITLE[location.pathname] ?? '影片與分析'

  return (
    <header className="flex shrink-0 items-center justify-between gap-4 border-b border-border bg-card px-4 py-3 lg:px-6">
      <div className="min-w-0">
        <p className="text-xs text-text-muted">AI 影片搜尋</p>
        <h1 className="truncate text-lg font-bold text-text-primary lg:text-xl">{pageTitle}</h1>
      </div>
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
