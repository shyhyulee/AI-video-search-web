import { useEffect, useRef, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import type { Video } from '../api/types'
import { formatCost, formatDateTime, formatDuration } from '../lib/format'
import { Badge } from './Badge'
import { Button } from './Button'
import { Card } from './Card'
import { VideoPlayer } from './VideoPlayer'
import { VideoSummaryAndDocument } from './VideoSummaryAndDocument'
import type { VideoCategory } from '../lib/videoCategory'

/** 觀看模式：左邊播影片、右邊放摘要與文件，版面對齊 YouTube 的觀看頁（P_03）。
 *
 * 從影片庫點文件裡的步驟時間戳進來。**右欄的時間戳仍然可點**，這正是這個版面
 * 存在的理由——邊看邊跳下一步，不必退回清單再點一次。
 *
 * 為什麼不是把播放器塞回詳細面板：那個面板只有半版寬，影片小、文件也被擠掉，
 * 兩件事都做不好。這裡把清單收起來，7:3 分給影片與文件。
 *
 * 為什麼不是全螢幕彈窗：Header 的頁籤導覽在全站每一頁都在，蓋掉它會讓這一個
 * 畫面變成例外；P_03 那張 YouTube 觀看頁的頂部導覽也是留著的。
 *
 * 刻意**不放**「在此影片內搜尋／整理成文件／重新分析」三顆按鈕：那是影片庫的
 * 管理動作，觀看時用不到，還會佔掉文件的空間。要用就退回影片庫。
 */
export function VideoWatchView({
  video,
  category,
  startSec,
  onBack,
}: {
  video: Video
  category: VideoCategory | undefined
  /** 進來時要跳到的秒數（點的那個步驟）。 */
  startSec: number
  onBack: () => void
}) {
  // { 秒數, 請求序號 }：重複點同一個步驟時秒數沒變，少了序號 VideoPlayer 的
  // effect 就不會重跑——手動把進度拖走之後點回同一步會沒反應。
  const [seek, setSeek] = useState({ sec: startSec, key: 0 })

  // 窄螢幕（<md）整個版面是上下堆疊的，時間戳在下方的文件裡——點了之後影片
  // 會在畫面外的上方開始播，使用者聽得到卻看不到。每次 seek 就把播放器捲進
  // 視野。桌機版播放器本來就在視野內，這行等於沒作用。
  const playerRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    playerRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [seek.key])

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex shrink-0 items-center gap-3">
        <Button
          variant="secondary"
          size="sm"
          icon={<ArrowLeft className="h-4 w-4" aria-hidden="true" />}
          onClick={onBack}
        >
          返回影片庫
        </Button>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <h2 className="truncate text-base font-bold text-text-primary">{video.title}</h2>
          {category && <Badge text={category} kind="primary" />}
        </div>
      </div>

      {/* 7:3。窄螢幕（<md）改上下堆疊：影片在上、文件在下，跟全站其他頁一致。 */}
      <div className="flex flex-col gap-4 md:min-h-0 md:flex-1 md:flex-row">
        <div ref={playerRef} className="flex w-full min-w-0 flex-col gap-2 md:min-h-0 md:w-2/3">
          {/* 依**寬度**定尺寸（`aspect-video`），不是讓它撐滿欄高——撐滿的話
              16:9 的影片在比較高的框裡會上下各留一條黑邊，白白吃掉空間。
              `max-h-full` 是欄位太矮時的保險，不讓播放器把下面那行 meta 擠出去。 */}
          <VideoPlayer
            videoId={video.id}
            startSec={seek.sec}
            seekKey={seek.key}
            title={video.title}
            className="aspect-video max-h-full object-contain"
          />
          <p className="shrink-0 text-sm text-text-secondary">
            {formatDuration(video.duration_sec)}
            {video.segment_count !== null ? `｜${video.segment_count} 個片段` : ''}
            ｜分析於 {formatDateTime(video.analyzed_at)}｜{formatCost(video.cost_usd)}
          </p>
        </div>

        <Card className="flex w-full min-w-0 flex-col md:min-h-0 md:w-1/3 md:overflow-auto">
          <VideoSummaryAndDocument
            video={video}
            onSeek={(sec) => setSeek((prev) => ({ sec, key: prev.key + 1 }))}
          />
        </Card>
      </div>
    </div>
  )
}
