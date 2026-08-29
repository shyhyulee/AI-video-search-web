import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { Header } from './components/Header'
import { MobileBottomNav } from './components/MobileBottomNav'
import { ToastProvider } from './components/Toast'
import { SearchScopeProvider } from './components/SearchScopeProvider'
import { VideosPage } from './pages/VideosPage'
import { LibraryPage } from './pages/LibraryPage'
import { SearchPage } from './pages/SearchPage'
import { ConversationPage } from './pages/ConversationPage'
import { YoutubeSearchPage } from './pages/YoutubeSearchPage'

/** 五個主頁籤，順序與 TopNav／MobileBottomNav 一致。 */
const PAGES = [
  { path: '/youtube', element: <YoutubeSearchPage /> },
  { path: '/videos', element: <VideosPage /> },
  { path: '/library', element: <LibraryPage /> },
  { path: '/search', element: <SearchPage /> },
  { path: '/conversation', element: <ConversationPage /> },
]

function App() {
  const { pathname } = useLocation()
  const isKnownPage = PAGES.some((p) => p.path === pathname)

  // 造訪過的頁籤才掛載——第一次點進去才付出初始化成本（例如「對話搜尋」會
  // 建立一筆 conversation、「影片庫」會拉整份清單），之後就一直留著不卸載。
  // 在 render 中呼叫自己的 setState 是 React 官方的「render 期間調整 state」
  // 用法：有 includes 擋著不會無限迴圈，React 會直接重跑這個 component，不會
  // 多畫一幀，比放進 useEffect 少一次閃爍。
  const [mountedPaths, setMountedPaths] = useState<string[]>([])
  if (isKnownPage && !mountedPaths.includes(pathname)) {
    setMountedPaths([...mountedPaths, pathname])
  }

  return (
    <ToastProvider>
      {/* 搜尋範圍要跨頁籤共用（影片庫設定 → 搜尋影片／對話搜尋兩頁都吃），
          所以 Provider 一定要包在 KeepAlivePage 外面。 */}
      <SearchScopeProvider>
        <div className="flex h-dvh flex-col">
          <Header />
          {/* 主導覽已移進 Header（TopNav），這裡不再有左右分欄；min-h-0 flex-1
              原本掛在包住 Sidebar 與 main 的 wrapper 上，拆掉 wrapper 後一定要
              搬到 <main> 自己身上，否則 main 會被內容撐高、蓋掉下面的
              MobileBottomNav。 */}
          <main className="min-h-0 min-w-0 flex-1 overflow-auto">
            {/* h-full 讓每個頁面內部的 min-h-0/flex-1/overflow-auto 雙欄捲動邏輯
                能正確拿到高度，這個 wrapper 一定要跟著給 h-full，不然頁面內容
                會退化成撐開高度、整頁一起捲動。 */}
            <div className="mx-auto h-full max-w-[1540px] p-4 lg:p-6">
              {/* relative 的定位基準刻意放在「沒有 padding」的這一層：隱藏中的
                  頁籤是 absolute inset-0，這樣它的框跟作用中頁籤（in-flow 的
                  h-full）完全一樣寬高，切回來時排版與捲動位置才不會位移。 */}
              <div className="relative h-full">
                {/* 未知路徑（含首頁 /）一律導到第一個頁籤。 */}
                {!isKnownPage && <Navigate to="/youtube" replace />}
                {PAGES.filter((p) => mountedPaths.includes(p.path)).map((p) => (
                  <KeepAlivePage key={p.path} active={p.path === pathname}>
                    {p.element}
                  </KeepAlivePage>
                ))}
              </div>
            </div>
          </main>
          <MobileBottomNav />
        </div>
      </SearchScopeProvider>
    </ToastProvider>
  )
}

/** 讓非作用中的頁籤留在 DOM 裡（只是隱藏起來），切走再切回來時該頁的 React
 * state 原封不動——搜尋關鍵字與結果、展開中的卡片、進行中的分析 job、對話
 * 記錄都還在。
 *
 * 隱藏用 `invisible absolute inset-0` 而不是 `hidden`（display:none）：
 * display:none 會讓元素失去 box，內部捲動容器的 scrollTop 被瀏覽器重設成 0，
 * 切回來會跳回最上面；visibility:hidden 保留 box，捲動位置原封不動，而且同樣
 * 不會被鍵盤 focus 到、也不會被螢幕閱讀器讀到，不需要另外加 inert／aria-hidden。 */
function KeepAlivePage({ active, children }: { active: boolean; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const wasActive = useRef(active)

  useEffect(() => {
    // 頁籤切走時把裡面還在播的影片停下來：頁面雖然看不見但還在 DOM 裡，不主動
    // 暫停的話 YouTube 內嵌播放器與 <video> 會在背景繼續出聲。暫停不會丟掉播放
    // 位置，切回來按播放就接著看。
    if (wasActive.current && !active) pauseMediaIn(ref.current)
    wasActive.current = active
  }, [active])

  return (
    <div ref={ref} className={active ? 'h-full' : 'invisible absolute inset-0'}>
      {children}
    </div>
  )
}

function pauseMediaIn(root: HTMLElement | null) {
  if (!root) return
  root.querySelectorAll('video').forEach((el) => el.pause())
  root.querySelectorAll('iframe').forEach((el) => {
    // 跨來源的 YouTube iframe 沒有 DOM API 可以控制，只能用 IFrame Player API
    // 的 postMessage 指令（embed 網址要帶 enablejsapi=1，見 YoutubeResultCard）。
    if (!el.src.includes('youtube')) return
    el.contentWindow?.postMessage(
      JSON.stringify({ event: 'command', func: 'pauseVideo', args: [] }),
      new URL(el.src).origin,
    )
  })
}

export default App
