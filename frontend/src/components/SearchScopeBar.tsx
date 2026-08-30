import { X } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { listVideos } from '../api/client'
import { libraryVideosKey } from '../lib/queryKeys'
import { useSearchScope } from '../lib/useSearchScope'

/** 目前搜尋範圍的 chips，「搜尋影片」與「對話搜尋」兩頁共用同一份狀態
 * （見 lib/useSearchScope.tsx）。沒有勾選任何影片時整條不顯示——「全部影片」
 * 是預設狀態，不需要佔一行去講。
 *
 * 影片標題從 ['videos', 'library'] 這個 query key 讀，跟 LibraryPage 完全相同，
 * react-query 直接共用快取、不會多打一次 API；還沒載到就先顯示「影片 #id」，
 * 不要因為等標題而讓 chips 整條晚一拍才出現。
 */
export function SearchScopeBar({ className = '' }: { className?: string }) {
  const { videoIds, clearScope, removeVideo } = useSearchScope()
  const { data: videos } = useQuery({ queryKey: libraryVideosKey(), queryFn: () => listVideos() })

  if (videoIds.length === 0) return null

  const titleOf = (id: number) => videos?.find((v) => v.id === id)?.title ?? `影片 #${id}`

  return (
    <div className={`flex flex-wrap items-center gap-2 text-sm ${className}`}>
      <span className="text-text-secondary">
        搜尋範圍：{videoIds.length} 支影片
      </span>
      {videoIds.map((id) => (
        <span
          key={id}
          className="inline-flex max-w-[16rem] items-center gap-1 rounded-full border border-border bg-sand px-3 py-1 text-text-primary"
        >
          <span className="truncate">{titleOf(id)}</span>
          <button
            type="button"
            onClick={() => removeVideo(id)}
            aria-label={`從搜尋範圍移除 ${titleOf(id)}`}
            className="shrink-0 rounded-full p-0.5 text-text-muted hover:bg-sand-strong hover:text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </span>
      ))}
      {/* 淺底上的文字色一律用 text-primary-hover，不用 text-primary（對比度，見 index.css）。 */}
      <button type="button" onClick={clearScope} className="font-bold text-primary-hover">
        清除範圍，改為全部影片
      </button>
    </div>
  )
}
