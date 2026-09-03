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
  /** 「請暫停」的請求識別碼，每次要求給一個新值（跟 `seekKey` 同一個慣用法）。
   *
   * 為什麼不是 `paused: boolean`：布林值代表「呼叫端持續主張播放狀態」，那會跟
   * 使用者自己按播放鍵打架——他一按播放，state 沒變、effect 不重跑，看起來沒事，
   * 但下次任何 re-render 都可能把它再按回暫停。用遞增的 key 表達的是「**這一刻**
   * 請暫停一次」，之後控制權還給使用者。
   *
   * 也不把 ref 交出去（見 onTimeChange 的說明）：呼叫端要的是「停一下」這個動作，
   * 不是整個 media element。 */
  pauseKey?: number
  /** 播放位置變動時回報目前秒數（含使用者拖動進度條、暫停時的微調）。
   *
   * 用 callback 而不是把 ref 交出去：呼叫端要的是「現在停在第幾秒」這個值，
   * 不是整個 media element 的控制權。給了 ref 就等於預設呼叫端可以自己
   * play/pause/改 src，那會跟上面那段 seek 邏輯打架。
   *
   * `timeupdate` 在播放中約每 250ms 觸發一次，所以呼叫端存進 state 前要自己
   * 決定精度（對話搜尋是取整數秒，見 ConversationPage）。 */
  onTimeChange?: (sec: number) => void
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
  pauseKey,
  onTimeChange,
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

  useEffect(() => {
    // undefined＝呼叫端沒有要用這個功能，連第一次掛載都不要動它。
    if (pauseKey === undefined) return
    videoRef.current?.pause()
  }, [pauseKey])

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
        onTimeChange?.(e.currentTarget.currentTime)
      }}
      // seeked 而不是只有 timeupdate：暫停狀態下拖動進度條不會觸發 timeupdate，
      // 而「停在某一格再提問」正是這個功能最主要的用法。
      onTimeUpdate={(e) => onTimeChange?.(e.currentTarget.currentTime)}
      onSeeked={(e) => onTimeChange?.(e.currentTarget.currentTime)}
    />
  )
}
