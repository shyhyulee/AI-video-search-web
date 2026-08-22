import { NavLink } from 'react-router-dom'

const NAV_ITEMS = [
  { to: '/videos', label: '影片與分析' },
  { to: '/library', label: '影片庫' },
  { to: '/search', label: '搜尋結果' },
  { to: '/conversation', label: '對話搜尋' },
]

/** 側邊導覽列，對應 Tkinter 版 ttk.Notebook 的頁籤（見
 * docs/07-ui-structure-and-features.md）；「處理紀錄」頁籤這次不做 Web
 * 版，見 docs/09-web-ui-migration-plan.md Phase 3 說明。 */
export function Sidebar() {
  return (
    <nav className="w-48 shrink-0 border-r border-border bg-card p-4">
      <ul className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              className={({ isActive }) =>
                `block rounded px-3 py-2 text-sm font-bold ${
                  isActive ? 'bg-badge-primary-bg text-primary' : 'text-text-secondary hover:bg-app-bg'
                }`
              }
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
