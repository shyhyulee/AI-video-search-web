import { useQuery } from '@tanstack/react-query'
import { getVideoDocument } from '../api/client'
import type { Video } from '../api/types'
import { videoDocumentKey } from '../lib/queryKeys'
import { LoadingSkeleton } from './LoadingSkeleton'
import { VideoDocumentView } from './VideoDocumentView'

/** 一支影片的「摘要 ＋ 整理出來的文件」。
 *
 * 兩個地方用它：影片庫的詳細面板（`VideoDetailPanel`）與觀看模式
 * （`VideoWatchView`）。抽出來是因為觀看模式要在播放器旁邊顯示同一份內容——
 * 複製一份的話，「摘要與文件之間怎麼排」這個決定就會有兩份實作。
 *
 * 摘要與文件原本是兩個頁籤，已合併成上下一段：兩者來自同一次 LLM 呼叫（文件的
 * overview 就是摘要），分成兩個頁籤等於要使用者自己去對照兩段講同一件事的文字。
 * 摘要固定在最上面，位置不隨有沒有文件而變。
 *
 * **自己查文件而不是由呼叫端傳進來**：query key 跟詳細面板共用
 * （`videoDocumentKey`），所以兩邊同時掛著也只有一份快取、一次請求。
 */
export function VideoSummaryAndDocument({
  video,
  onSeek,
  isGenerating = false,
  status,
}: {
  video: Video
  /** 點文件裡的步驟時間戳時呼叫。不給就是純文字，見 VideoDocumentView。 */
  onSeek?: (sec: number) => void
  /** 正在重新整理文件——這時要顯示骨架屏而不是舊內容。 */
  isGenerating?: boolean
  /** 整理成文件的進行中／結果訊息，由呼叫端提供（只有詳細面板有那顆按鈕）。 */
  status?: string
}) {
  // `video.document_type` 是清單就有的輕量旗標，用它當 enabled 條件：沒整理過
  // 的影片完全不會打這支 API（後端那時會回 404，那是正常狀態不是錯誤，不該讓
  // react-query 一直重試）。
  const documentQuery = useQuery({
    queryKey: videoDocumentKey(video.id),
    queryFn: () => getVideoDocument(video.id),
    enabled: video.document_type !== null,
    staleTime: Infinity, // 文件只有按下「整理成文件」才會變，不用自動重取
  })

  return (
    <>
      <h4 className="mb-1 text-sm font-bold text-text-primary">摘要</h4>
      <p className="text-sm leading-relaxed text-text-primary">
        {video.summary ??
          (video.status === 'analyzed'
            ? '尚未產生摘要，按上方「整理成文件」會一併產生。'
            : '這支影片分析失敗，沒有片段可以產生摘要。')}
      </p>

      <div className="mt-4 border-t border-border pt-4">
        {isGenerating || documentQuery.isLoading ? (
          <LoadingSkeleton variant="list-item" count={3} />
        ) : documentQuery.data ? (
          <VideoDocumentView document={documentQuery.data.document} onSeek={onSeek} />
        ) : (
          <p className="text-sm leading-relaxed text-text-secondary">
            {video.status === 'analyzed'
              ? '尚未整理成文件。按上方「整理成文件」，系統會依影片內容判斷要產生流程 SOP、教學步驟、課堂筆記，還是內容紀錄，並同時更新上方的摘要。'
              : '這支影片分析失敗，沒有片段可以整理成文件。'}
          </p>
        )}
        {status && (
          <p className="mt-2 text-sm text-text-secondary" aria-live="polite">
            {status}
          </p>
        )}
      </div>
    </>
  )
}
