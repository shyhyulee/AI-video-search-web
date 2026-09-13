import { createContext, useContext } from 'react'

/** 全站共用的「搜尋範圍」：使用者在影片庫勾選的那批影片 id，空陣列代表不限定
 * （搜全部影片）。
 *
 * 為什麼要一份共用狀態、而不是像以前那樣用 `?video_id=` 帶在 URL 上：範圍現在
 * 同時被「搜尋影片」與「對話搜尋」兩頁使用，兩頁各留一份 local state 一定會
 * 分岔——使用者在搜尋頁移掉一支，切到對話頁還是舊的那批。頁籤是 keep-alive
 * （見 App.tsx 的 KeepAlivePage），所以這份 state 本來就不會因為切頁而遺失，
 * 這裡只是把它從單一頁面提到共用層。
 *
 * 刻意只存 id、不存標題：標題從 react-query 的 ['videos', 'library'] 快取查就好
 * （跟 LibraryPage 同一個 query key，不會多打一次 API），存兩份會有影片改名或
 * 被刪除之後顯示過期資料的問題。
 *
 * 檔案切法跟 Toast 一樣（lib/useToast.ts + components/Toast.tsx）：context 與
 * hook 放這裡、Provider 元件放 components/，這樣每個檔案只 export 同一類東西，
 * Fast Refresh 才不會失效。
 */
export interface SearchScopeValue {
  videoIds: number[]
  setScope: (ids: number[]) => void
  clearScope: () => void
  removeVideo: (id: number) => void
}

export const SearchScopeContext = createContext<SearchScopeValue | null>(null)

/** 讀取全站共用的搜尋範圍，必須在 SearchScopeProvider 內使用。 */
export function useSearchScope(): SearchScopeValue {
  const ctx = useContext(SearchScopeContext)
  if (!ctx) throw new Error('useSearchScope 必須在 SearchScopeProvider 內使用')
  return ctx
}
