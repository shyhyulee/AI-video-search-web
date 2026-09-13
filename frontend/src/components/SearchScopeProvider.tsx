import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { SearchScopeContext } from '../lib/useSearchScope'

/** 提供全站共用的搜尋範圍。要包在 App.tsx 的 KeepAlivePage 外面，範圍才能跨
 * 頁籤共用（影片庫設定 → 搜尋影片／對話搜尋兩頁都吃）。語意說明見
 * lib/useSearchScope.ts。 */
export function SearchScopeProvider({ children }: { children: ReactNode }) {
  const [videoIds, setVideoIds] = useState<number[]>([])

  const setScope = useCallback((ids: number[]) => setVideoIds([...ids]), [])
  const clearScope = useCallback(() => setVideoIds([]), [])
  const removeVideo = useCallback(
    (id: number) => setVideoIds((prev) => prev.filter((v) => v !== id)),
    [],
  )

  const value = useMemo(
    () => ({ videoIds, setScope, clearScope, removeVideo }),
    [videoIds, setScope, clearScope, removeVideo],
  )
  return <SearchScopeContext.Provider value={value}>{children}</SearchScopeContext.Provider>
}
