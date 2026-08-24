import { useEffect, useRef } from 'react'
import { getStreamUrl } from '../api/client'

interface VideoPlayerProps {
  videoId: number
  startSec: number
  title?: string
  className?: string
}

/** 共用影片播放器：同一支影片內切換片段直接 seek，不重新載入整支影片；
 * 換成不同影片時讓瀏覽器自然重新載入（src 變更），由 onLoadedMetadata 處理 seek。
 * 取代 SearchPage／ConversationPage 各自手刻、且都得靠呼叫端記得寫
 * key={video_id} 才會正確 remount 的重複邏輯。 */
export function VideoPlayer({ videoId, startSec, title, className = '' }: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const loadedVideoId = useRef<number | null>(null)

  useEffect(() => {
    const el = videoRef.current
    if (el && loadedVideoId.current === videoId) {
      el.currentTime = startSec
      el.play().catch(() => {})
    }
  }, [videoId, startSec])

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
        e.currentTarget.play().catch(() => {})
      }}
    />
  )
}
