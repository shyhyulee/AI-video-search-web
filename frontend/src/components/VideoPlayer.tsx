import { useEffect, useRef } from 'react'
import { getStreamUrl } from '../api/client'

interface VideoPlayerProps {
  videoId: number
  startSec: number
  title?: string
  className?: string
  /** 載入／seek 完成後要不要直接播。使用者主動點某個片段時是 true（點了就想
   * 看）；程式自己帶出來的預設選取要傳 false，只把畫面停在該時間點，不要
   * 未經指示就出聲。 */
  autoPlay?: boolean
  /** 「請跳到 startSec」的請求識別碼，每次要求給一個新值。
   *
   * 沒有它的話，重複點同一個時間點不會有反應：`startSec` 值沒變，下面 effect
   * 的 deps 就沒變，effect 不會重跑——使用者手動把進度拖走之後，再點同一個
   * 步驟就回不去了。不傳＝維持原本行為（搜尋頁與對話頁沒有這個需求，它們每次
   * 選的都是不同片段）。 */
  seekKey?: number
}

/** 共用影片播放器：同一支影片內切換片段直接 seek，不重新載入整支影片；
 * 換成不同影片時讓瀏覽器自然重新載入（src 變更），由 onLoadedMetadata 處理 seek。
 * 取代 SearchPage／ConversationPage 各自手刻、且都得靠呼叫端記得寫
 * key={video_id} 才會正確 remount 的重複邏輯。 */
export function VideoPlayer({
  videoId,
  startSec,
  title,
  className = '',
  autoPlay = true,
  seekKey,
}: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const loadedVideoId = useRef<number | null>(null)

  useEffect(() => {
    const el = videoRef.current
    if (el && loadedVideoId.current === videoId) {
      el.currentTime = startSec
      // autoPlay 放進 deps：使用者點的是「已經選中的那一筆」時 videoId／
      // startSec 都沒變，只有 autoPlay 從 false 翻成 true，沒有它這次點擊
      // 就不會播。
      if (autoPlay) el.play().catch(() => {})
    }
  }, [videoId, startSec, autoPlay, seekKey])

  return (
    <video
      ref={videoRef}
      src={getStreamUrl(videoId)}
      controls
      aria-label={title}
      className={`w-full rounded bg-black ${className}`}
      onLoadedMetadata={(e) => {
        loadedVideoId.current = videoId
        e.currentTarget.currentTime = startSec
        if (autoPlay) e.currentTarget.play().catch(() => {})
      }}
    />
  )
}
