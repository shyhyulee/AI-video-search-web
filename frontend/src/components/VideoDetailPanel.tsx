import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { generateVideoDocument, getVideoDocument, reanalyzeVideo } from '../api/client'
import type { Job, Video } from '../api/types'
import { formatCost, formatDateTime, formatDuration, formatTimestamp } from '../lib/format'
import { isActive } from '../lib/jobStatus'
import { libraryVideosKey, statsKey, videoDocumentKey } from '../lib/queryKeys'
import { useJobPolling } from '../lib/useJobPolling'
import { useJobSettlement } from '../lib/useJobSettlement'
import type { VideoCategory } from '../lib/videoCategory'
import { Badge } from './Badge'
import { Button, IconButton } from './Button'
import { LoadingSkeleton } from './LoadingSkeleton'
import { VideoDocumentView } from './VideoDocumentView'
import { VideoPlayer } from './VideoPlayer'

export function VideoDetailPanel({
  video,
  category,
  activeJob,
  onSearchInVideo,
}: {
  video: Video
  /** 由 `classifyVideo()` 從標題與摘要推導，不是資料庫欄位，見 lib/videoCategory.ts。 */
  category: VideoCategory | undefined
  /** 後端回報的、這支影片進行中的分析工作。重新整理後靠它把進度接回來——
   * `reanalysisJobId` 只活在 React state，F5 就沒了。 */
  activeJob: Job | undefined
  onSearchInVideo: (video: Video) => void
}) {
  const queryClient = useQueryClient()
  const [documentStatus, setDocumentStatus] = useState('')
  // 點文件裡的時間戳才會出現播放器。**刻意不常駐**：這個面板的滿版縮圖就是因為
  // 「純裝飾卻吃掉 42vh」被移除的（見下方註解），而一份 SOP 有二三十個步驟，
  // 最缺的就是垂直空間。使用者主動要看才給，看完可以收掉。
  //
  // 存的是 { 秒數, 請求序號 } 而不是單一秒數：重複點同一個步驟時秒數沒變，
  // 少了序號就不會重新 seek——手動把進度拖走之後點回同一步會沒反應。
  const [playRequest, setPlayRequest] = useState<{ sec: number; key: number } | null>(null)
  const playAt = (sec: number) =>
    setPlayRequest((prev) => ({ sec, key: (prev?.key ?? 0) + 1 }))
  const [reanalysisJobId, setReanalysisJobId] = useState<number | null>(null)

  // `video.document_type` 是清單就有的輕量旗標，用它當 enabled 條件：沒整理過
  // 的影片完全不會打這支 API（後端那時會回 404，那是正常狀態不是錯誤，不該讓
  // react-query 一直重試）。
  const documentQuery = useQuery({
    queryKey: videoDocumentKey(video.id),
    queryFn: () => getVideoDocument(video.id),
    enabled: video.document_type !== null,
    staleTime: Infinity, // 文件只有按下「整理成文件」才會變，不用自動重取
  })

  const documentMutation = useMutation({
    mutationFn: () => generateVideoDocument(video.id),
    onSuccess: (resp) => {
      setDocumentStatus('✓ 文件與摘要已更新')
      // 直接把結果塞進快取，省掉一次來回。清單一定要 invalidate——摘要也是這
      // 一次呼叫產出的（見後端 video_service.generate_document），上方那段
      // 摘要讀的是清單裡的 video.summary，不重取就不會跟著換。
      queryClient.setQueryData(videoDocumentKey(video.id), resp)
      queryClient.invalidateQueries({ queryKey: libraryVideosKey() })
      queryClient.invalidateQueries({ queryKey: statsKey() })
    },
    onError: (err: Error) => setDocumentStatus(`整理失敗：${err.message}`),
  })

  const reanalyzeMutation = useMutation({
    mutationFn: () => reanalyzeVideo(video.id),
    onSuccess: (job) => {
      setReanalysisJobId(job.id)
      queryClient.invalidateQueries({ queryKey: libraryVideosKey() })
    },
  })

  useEffect(() => {
    // 把後端撈回來的進行中工作接上輪詢。接上之後就交給 useJobPolling——
    // job 到終態會離開 activeJob，但 reanalysisJobId 留著，才顯示得出結果。
    // oxlint-disable-next-line react/set-state-in-effect
    if (activeJob && activeJob.id !== reanalysisJobId) setReanalysisJobId(activeJob.id)
  }, [activeJob, reanalysisJobId])

  const jobQuery = useJobPolling(reanalysisJobId)
  const job = jobQuery.data

  // 重新分析結束（成功或失敗）要讓列表與統計卡跟著更新。去重由
  // useJobSettlement 負責（見那裡的說明）。
  //
  // 這裡刻意不跳 toast。原本會跳「重新分析完成」，結果是無限迴圈：
  // `toast` 來自 ToastContext，跳一則通知會讓 ToastProvider 重繪、context
  // value 換成新物件，effect 的 deps 就變了、再跑一次、再跳一則……畫面被同
  // 一則訊息疊滿。ToastProvider 的 value 已經改成 useMemo 穩定住（見
  // components/Toast.tsx），但這則通知本身也不需要——影片跑完會自己從
  // 「分析中」變回「分析完成」，畫面上看得出來。
  useJobSettlement([job], () => {
    queryClient.invalidateQueries({ queryKey: libraryVideosKey() })
    queryClient.invalidateQueries({ queryKey: statsKey() })
  })

  // 影片自己的 status 也算 busy：重新整理後 job 還沒接回來的那幾秒，按鈕
  // 不能是可按的——後端會回 409，而且摘要／搜尋這時看到的是上一輪的結果。
  const analyzing = video.status === 'analyzing' || isActive(job?.status)
  const busy = documentMutation.isPending || reanalyzeMutation.isPending || analyzing

  return (
    <div className="flex flex-col gap-3 md:h-full">
      {/* 這裡原本有一張滿版縮圖。移除的理由：它是純裝飾（面板裡沒有播放器，
          點了不會播），卻吃掉 md:max-h-[42vh] 的高度——而一份 SOP 有二三十個
          步驟，最缺的就是垂直空間。清單列的小縮圖（VideoListItem）還在，辨識
          影片靠那裡就夠了。 */}
      <div className="shrink-0">
        {/* flex-wrap：標題長的時候讓分類標籤換到下一行，不要把標題擠成一長串省略號。 */}
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-base font-bold text-text-primary">{video.title}</h3>
          {category && <Badge text={category} kind="primary" />}
        </div>
        <p className="mt-1 text-sm text-text-secondary">
          {formatDuration(video.duration_sec)}
          {video.segment_count !== null ? `｜${video.segment_count} 個片段` : ''}
          ｜分析於 {formatDateTime(video.analyzed_at)}｜{formatCost(video.cost_usd)}
        </p>
      </div>

      <div className="flex shrink-0 flex-wrap gap-2">
        <Button variant="primary" size="sm" disabled={video.status !== 'analyzed' || busy} onClick={() => onSearchInVideo(video)}>
          在此影片內搜尋
        </Button>
        {/* 原本這裡有「重新產生摘要」與「整理成文件」兩顆。摘要那顆移除了——
            文件的 overview 一稿兩用，整理文件時會一起更新摘要（見後端
            video_service.generate_document），兩顆按鈕產出高度重疊的文字沒有
            意義。後端的 POST /videos/{id}/summary 端點還在，只是前端不再呼叫，
            照 uploadVideo() 的先例。 */}
        <Button
          variant="secondary"
          size="sm"
          disabled={video.status !== 'analyzed' || busy}
          onClick={() => {
            setDocumentStatus('整理中…會一併更新摘要，影片越長越久，請稍候')
            documentMutation.mutate()
          }}
        >
          {video.document_type ? '重新整理文件' : '整理成文件'}
        </Button>
        <Button variant="secondary" size="sm" disabled={busy} onClick={() => reanalyzeMutation.mutate()}>
          重新分析
        </Button>
      </div>

      {/* analyzing 也要顯示，不能只看 job：重新整理之後 job 還沒接回來，
          但影片的 status 已經說得很清楚。階段文字優先用 job 的（比較即時），
          沒有就退回 videos.pipeline_stage（analyzer 每個階段都會寫進 DB）。 */}
      {(job || analyzing) && (
        <p className="shrink-0 text-sm text-text-secondary" aria-live="polite">
          {job?.status === 'completed'
            ? '✓ 重新分析完成'
            : job?.status === 'failed'
              ? `重新分析失敗：${job.error_message}`
              : `重新分析中…${job?.stage ?? video.pipeline_stage ?? ''}`}
        </p>
      )}

      {playRequest && (
        <div className="shrink-0">
          <div className="mb-1 flex items-center justify-between gap-2">
            <p className="text-xs text-text-secondary" aria-live="polite">
              從 {formatTimestamp(playRequest.sec)} 開始播放
            </p>
            <IconButton
              icon={<X className="h-4 w-4" />}
              aria-label="關閉播放器"
              onClick={() => setPlayRequest(null)}
            />
          </div>
          {/* max-h 限制是必要的：沒有它，16:9 的播放器在半版寬的面板裡會吃掉
              大半個高度，下面的步驟就只剩幾行。object-contain 讓直式影片也不
              會被裁掉。 */}
          <VideoPlayer
            videoId={video.id}
            startSec={playRequest.sec}
            seekKey={playRequest.key}
            title={video.title}
            className="max-h-[32vh] object-contain"
          />
        </div>
      )}

      {/* 內容區放在最下面：長度不固定（幾行到二三十個步驟都有可能），擺在中間
          會把按鈕推到不固定的位置，換一支影片按鈕就跳一次。放最後之後，上面的
          標題／標籤／按鈕在每支影片都固定在同樣的高度。
          它同時是整個面板唯一會捲動的地方——上面全是 shrink-0，這裡吃掉剩下的
          高度（md:flex-1），真的塞不下才在自己內部捲，卡片本身不捲。

          摘要與文件原本是兩個頁籤，已合併成上下一段：兩者來自同一次 LLM 呼叫
          （文件的 overview 就是摘要），分成兩個頁籤等於要使用者自己去對照兩段
          講同一件事的文字。摘要固定在最上面，位置不隨有沒有文件而變。 */}
      <div className="md:min-h-0 md:flex-1 md:overflow-auto">
        <h4 className="mb-1 text-sm font-bold text-text-primary">摘要</h4>
        <p className="text-sm leading-relaxed text-text-primary">
          {video.summary ??
            (video.status === 'analyzed'
              ? '尚未產生摘要，按上方「整理成文件」會一併產生。'
              : '這支影片分析失敗，沒有片段可以產生摘要。')}
        </p>

        <div className="mt-4 border-t border-border pt-4">
          {documentMutation.isPending || documentQuery.isLoading ? (
            <LoadingSkeleton variant="list-item" count={3} />
          ) : documentQuery.data ? (
            <VideoDocumentView document={documentQuery.data.document} onSeek={playAt} />
          ) : (
            <p className="text-sm leading-relaxed text-text-secondary">
              {video.status === 'analyzed'
                ? '尚未整理成文件。按上方「整理成文件」，系統會依影片內容判斷要產生流程 SOP、教學步驟、課堂筆記，還是內容紀錄，並同時更新上方的摘要。'
                : '這支影片分析失敗，沒有片段可以整理成文件。'}
            </p>
          )}
          {documentStatus && (
            <p className="mt-2 text-sm text-text-secondary" aria-live="polite">
              {documentStatus}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
