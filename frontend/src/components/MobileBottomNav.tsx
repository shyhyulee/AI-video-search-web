import { NavLink } from 'react-router-dom'
import { Film, Library, Search, MessageCircle } from 'lucide-react'

const NAV_ITEMS = [
  { to: '/videos', label: '影片與分析', icon: Film },
  { to: '/library', label: '影片庫', icon: Library },
  { to: '/search', label: '搜尋結果', icon: Search },
  { to: '/conversation', label: '對話搜尋', icon: MessageCircle },
]

/** 取代 Sidebar 的底部導覽列，只在 ≤900px（md 斷點以下）顯示。 */
export function MobileBottomNav() {
  return (
    <nav className="flex shrink-0 border-t border-border bg-card md:hidden">
      {NAV_ITEMS.map(({ to, label, icon: IconComp }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) =>
            `flex flex-1 flex-col items-center gap-1 py-2 text-xs font-bold ${
              isActive ? 'text-primary-hover' : 'text-text-secondary'
            }`
          }
        >
          <IconComp className="h-5 w-5" aria-hidden="true" />
          {label}
        </NavLink>
      ))}
    </nav>
  )
}
