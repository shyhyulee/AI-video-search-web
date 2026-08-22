import { Navigate, Route, Routes } from 'react-router-dom'
import { Header } from './components/Header'
import { Sidebar } from './components/Sidebar'
import { VideosPage } from './pages/VideosPage'
import { LibraryPage } from './pages/LibraryPage'
import { SearchPage } from './pages/SearchPage'
import { ConversationPage } from './pages/ConversationPage'

function App() {
  return (
    <div className="flex h-screen flex-col">
      <Header />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-auto p-6">
          <Routes>
            <Route path="/" element={<Navigate to="/videos" replace />} />
            <Route path="/videos" element={<VideosPage />} />
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/conversation" element={<ConversationPage />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}

export default App
