import { NavLink } from 'react-router-dom'
import { Film, Library, Search, MessageCircle, MonitorPlay } from 'lucide-react'

const NAV_ITEMS = [
  { to: '/videos', label: '影片與分析', icon: Film },
  { to: '/library', label: '影片庫', icon: Library },
  { to: '/search', label: '搜尋結果', icon: Search },
  { to: '/conversation', label: '對話搜尋', icon: MessageCircle },
  // lucide 這個版本已移除品牌圖示（沒有 Youtube icon），用 MonitorPlay 代替。
  { to: '/youtube', label: 'YouTube 搜尋', icon: MonitorPlay },
]

/** Header 中段的主導覽：≥1180px 顯示圖示＋文字（實測五個頁籤含 padding 約
 * 620px，加上品牌區 141px 與統計卡 258px 仍在 1180px 內），900–1180px 收合
 * 成僅圖示（約 236px），≤900px 隱藏改用 MobileBottomNav。
 *
 * 原本是左側 Sidebar，改成頂部橫向後主內容多出 240px 寬度；收合的三段邏輯
 * 跟 Sidebar 時期相同，只是方向從垂直換成水平。 */
export function TopNav() {
  // flex-1 撐開中段，把統計卡推到最右；≤900px 整個 nav hidden 時，Header 的
  // justify-between 會讓品牌與統計卡各自靠邊，版面不會塌。
  return (
    <nav className="hidden min-w-0 flex-1 items-center gap-1 md:flex">
      {NAV_ITEMS.map(({ to, label, icon: IconComp }) => (
        <NavLink
          key={to}
          to={to}
          title={label}
          className={({ isActive }) =>
            `flex h-10 shrink-0 items-center gap-2 rounded-xl px-3 text-sm font-bold ${
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
