import { NavLink } from 'react-router-dom'
import { Film, Library, Search, MessageCircle } from 'lucide-react'

const NAV_ITEMS = [
  { to: '/videos', label: '影片與分析', icon: Film },
  { to: '/library', label: '影片庫', icon: Library },
  { to: '/search', label: '搜尋結果', icon: Search },
  { to: '/conversation', label: '對話搜尋', icon: MessageCircle },
]

/** 桌機／筆電 Sidebar：≥1180px 完整寬度＋文字，900–1180px 收合成僅圖示的 rail，
 * ≤900px 隱藏改用 MobileBottomNav。 */
export function Sidebar() {
  return (
    <nav className="hidden shrink-0 flex-col gap-1 border-r border-border bg-card p-3 md:flex md:w-16 lg:w-60 lg:p-4">
      {NAV_ITEMS.map(({ to, label, icon: IconComp }) => (
        <NavLink
          key={to}
          to={to}
          title={label}
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-bold ${
              isActive ? 'bg-primary-soft text-primary-hover' : 'text-text-secondary hover:bg-sand'
            }`
          }
        >
          <IconComp className="h-5 w-5 shrink-0" aria-hidden="true" />
          <span className="hidden lg:inline">{label}</span>
        </NavLink>
      ))}
    </nav>
  )
}
