import { Navigate, Route, Routes } from 'react-router-dom'
import { Header } from './components/Header'
import { MobileBottomNav } from './components/MobileBottomNav'
import { ToastProvider } from './components/Toast'
import { VideosPage } from './pages/VideosPage'
import { LibraryPage } from './pages/LibraryPage'
import { SearchPage } from './pages/SearchPage'
import { ConversationPage } from './pages/ConversationPage'
import { YoutubeSearchPage } from './pages/YoutubeSearchPage'

function App() {
  return (
    <ToastProvider>
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
            <Routes>
              <Route path="/" element={<Navigate to="/videos" replace />} />
              <Route path="/videos" element={<VideosPage />} />
              <Route path="/library" element={<LibraryPage />} />
              <Route path="/search" element={<SearchPage />} />
              <Route path="/conversation" element={<ConversationPage />} />
              <Route path="/youtube" element={<YoutubeSearchPage />} />
            </Routes>
          </div>
        </main>
        <MobileBottomNav />
      </div>
    </ToastProvider>
  )
}

export default App
