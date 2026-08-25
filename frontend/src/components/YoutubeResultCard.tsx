import { useEffect, useId, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronUp, Copy, ExternalLink, ImageOff, Play, Sparkles, X } from 'lucide-react'
import { analyzeVideo, downloadYoutube } from '../api/client'
import { ApiError } from '../api/types'
import type { YoutubeSearchItem } from '../api/types'
import { formatDuration, formatViewCount } from '../lib/format'
import { useJobPolling } from '../lib/useJobPolling'
import { Button } from './Button'
import { Card } from './Card'
import { useToast } from '../lib/useToast'

interface YoutubeResultCardProps {
  item: YoutubeSearchItem
}

/** YouTube 搜尋結果卡片：收合時只有縮圖／標題／頻道資訊，「播放」就地把縮圖
 * 換成 YouTube 內嵌播放器（不用離開這一頁確認影片內容），「開始分析」直接跑
 * 下載 → 分析兩段 job（等同「影片與分析」頁貼網址下載再勾選分析），點
 * 「查看詳情」在卡片內就地展開網址與說明（不用 Modal，窄螢幕不會擋住畫面）。
 * 展開／播放／分析狀態都放在卡片內部，多張可以同時進行；外層 grid 記得加
 * items-start，不然展開一張會把同一列其他卡片一起撐高。 */
export function YoutubeResultCard({ item }: YoutubeResultCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [thumbnailFailed, setThumbnailFailed] = useState(false)
  const toast = useToast()
  const queryClient = useQueryClient()
  const detailId = useId()

  // 拿不到觀看數（部分直播／下架中的影片）就整段省略，不要顯示「-- 次觀看」
  const facts = [
    formatDuration(item.duration_sec),
    item.view_count === null ? '' : `${formatViewCount(item.view_count)}次觀看`,
  ]
    .filter(Boolean)
    .join(' ・ ')

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(item.url)
      toast.show('已複製影片網址', 'success')
    } catch {
      toast.show('複製失敗，請手動選取網址', 'error')
    }
  }

  // --- 開始分析：下載 job 完成後接分析 job ---
  const [downloadJobId, setDownloadJobId] = useState<number | null>(null)
  const [analysisJobId, setAnalysisJobId] = useState<number | null>(null)
  const [failure, setFailure] = useState('')
  // 兩段 job 都是輪詢查詢，同一個終態會被讀到很多次；用 ref 記下已經處理過的
  // job id，確保「接下一段」與「收尾」各只做一次。
  const handledDownload = useRef<number | null>(null)
  const handledAnalysis = useRef<number | null>(null)

  const downloadJob = useJobPolling(downloadJobId).data
  const analysisJob = useJobPolling(analysisJobId).data

  const invalidateAfterChange = () => {
    queryClient.invalidateQueries({ queryKey: ['videos', 'pending'] })
    queryClient.invalidateQueries({ queryKey: ['videos', 'library'] })
    queryClient.invalidateQueries({ queryKey: ['stats'] })
  }

  const analyzeMutation = useMutation({
    mutationFn: (videoId: number) => analyzeVideo(videoId),
    onSuccess: (job) => setAnalysisJobId(job.id),
    onError: (err: Error) =>
      setFailure(
        err instanceof ApiError && err.code === 'DURATION_LIMIT_EXCEEDED'
          ? '影片長度超過分析上限'
          : `無法開始分析：${err.message}`,
      ),
  })

  const downloadMutation = useMutation({
    mutationFn: () => downloadYoutube(item.url),
    onSuccess: (job) => setDownloadJobId(job.id),
    onError: (err: Error) => setFailure(`下載失敗：${err.message}`),
  })

  useEffect(() => {
    if (!downloadJob || handledDownload.current === downloadJob.id) return
    if (downloadJob.status === 'completed' && downloadJob.video_id !== null) {
      handledDownload.current = downloadJob.id
      // 影片已經進 DB（待分析），先讓清單／統計反映出來再送分析。
      invalidateAfterChange()
      analyzeMutation.mutate(downloadJob.video_id)
    } else if (downloadJob.status === 'failed') {
      handledDownload.current = downloadJob.id
      // 來源是輪詢查詢（外部系統）而非 DOM 事件，ref 已擋掉重複執行。
      // oxlint-disable-next-line react/set-state-in-effect
      setFailure(`下載失敗：${downloadJob.error_message ?? '未知錯誤'}`)
    }
    // analyzeMutation 每次 render 都是新物件，放進 deps 會讓 effect 每輪都跑；
    // 真正的觸發條件只有 downloadJob 的狀態變化。
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [downloadJob])

  useEffect(() => {
    if (!analysisJob || handledAnalysis.current === analysisJob.id) return
    if (analysisJob.status === 'completed') {
      handledAnalysis.current = analysisJob.id
      invalidateAfterChange()
      toast.show(`「${item.title}」分析完成`, 'success')
    } else if (analysisJob.status === 'failed') {
      handledAnalysis.current = analysisJob.id
      invalidateAfterChange()
      // oxlint-disable-next-line react/set-state-in-effect
      setFailure(`分析失敗：${analysisJob.error_message ?? '未知錯誤'}`)
    }
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisJob])

  const downloading =
    downloadMutation.isPending || (downloadJob ? downloadJob.status === 'queued' || downloadJob.status === 'running' : false)
  const analyzing =
    analyzeMutation.isPending || (analysisJob ? analysisJob.status === 'queued' || analysisJob.status === 'running' : false)
  const busy = downloading || analyzing
  const done = analysisJob?.status === 'completed'

  // 兩段 job 共用一條進度條：下載中看下載 job，其餘看分析 job。
  const activeJob = downloading ? downloadJob : analysisJob
  const progressText = (() => {
    if (failure) return failure
    if (done) return '✓ 分析完成，可到「搜尋結果」頁查詢'
    if (downloadMutation.isPending) return '準備下載…'
    if (downloading) return downloadJob?.progress_message ?? '下載中…'
    if (analyzeMutation.isPending || analysisJob?.status === 'queued') return '排隊分析中…'
    if (analyzing) return analysisJob?.stage ?? '分析中…'
    return ''
  })()

  const onAnalyzeClicked = () => {
    setFailure('')
    handledDownload.current = null
    handledAnalysis.current = null
    setAnalysisJobId(null)
    downloadMutation.mutate()
  }

  return (
    <Card padding="none" elevated className="flex flex-col overflow-hidden">
      {/* 播放時整塊媒體區換成 YouTube 內嵌播放器；用 nocookie 網域少帶一點
          追蹤 cookie，行為與 www.youtube.com/embed 相同。enablejsapi=1 是給
          App.tsx 的 KeepAlivePage 用的：頁籤切走時要能 postMessage 叫它暫停，
          不然這張卡片留在 DOM 裡會在背景繼續播。 */}
      {playing ? (
        <iframe
          src={`https://www.youtube-nocookie.com/embed/${item.video_id}?autoplay=1&rel=0&enablejsapi=1`}
          title={item.title}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
          className="aspect-video w-full border-0 bg-black"
        />
      ) : item.thumbnail_url && !thumbnailFailed ? (
        <img
          src={item.thumbnail_url}
          alt=""
          loading="lazy"
          className="aspect-video w-full bg-sand object-cover"
          onError={() => setThumbnailFailed(true)}
        />
      ) : (
        <div className="flex aspect-video w-full items-center justify-center bg-sand text-text-muted">
          <ImageOff className="h-6 w-6" aria-hidden="true" />
        </div>
      )}

      <div className="flex flex-1 flex-col gap-2 p-3">
        {/* 標題固定佔兩行高、meta 固定一行（truncate），讓同一列卡片的按鈕
            對齊。grid 用 items-start 時卡片各自算高度，不這樣做的話標題一行
            或兩行、meta 有沒有換行都會讓按鈕高低不一。 */}
        <h3 className="line-clamp-2 min-h-[2.4rem] text-sm leading-snug font-bold text-text-primary" title={item.title}>
          {item.title}
        </h3>
        {/* 只有頻道名長度不可控，所以只讓它 truncate；時長與觀看數固定短，
            永遠完整顯示，否則長頻道名會把觀看數擠成「7....」。 */}
        <p className="flex items-center text-xs text-text-secondary">
          {item.channel && (
            <>
              <span className="truncate">{item.channel}</span>
              <span className="shrink-0 px-1">・</span>
            </>
          )}
          <span className="shrink-0">{facts}</span>
        </p>

        {/* mt-auto 掛在按鈕區最外層，讓標題／meta 高度不一時按鈕仍貼齊卡片底部。 */}
        <div className="mt-auto flex flex-col gap-2">
          <div className="grid grid-cols-2 gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setPlaying((prev) => !prev)}
              icon={
                playing ? <X className="h-4 w-4" aria-hidden="true" /> : <Play className="h-4 w-4" aria-hidden="true" />
              }
            >
              {playing ? '關閉播放' : '播放'}
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={busy}
              disabled={busy || done}
              onClick={onAnalyzeClicked}
              icon={<Sparkles className="h-4 w-4" aria-hidden="true" />}
            >
              {done ? '已分析' : '開始分析'}
            </Button>
          </div>

          {(busy || progressText) && (
            <div>
              {busy && (
                <div className="mb-1 h-1.5 overflow-hidden rounded-full bg-sand">
                  <div
                    className="h-full bg-primary transition-all"
                    style={{ width: `${activeJob?.progress_percent ?? 0}%` }}
                  />
                </div>
              )}
              <p className={`text-xs ${failure ? 'text-error' : 'text-text-secondary'}`} aria-live="polite">
                {progressText}
              </p>
            </div>
          )}

          <Button
            variant="ghost"
            size="sm"
            className="w-full"
            aria-expanded={expanded}
            aria-controls={detailId}
            onClick={() => setExpanded((prev) => !prev)}
            icon={
              expanded ? <ChevronUp className="h-4 w-4" aria-hidden="true" /> : <ChevronDown className="h-4 w-4" aria-hidden="true" />
            }
          >
            {expanded ? '收合詳情' : '查看詳情'}
          </Button>
        </div>
      </div>

      {expanded && (
        <div id={detailId} className="border-t border-border bg-surface-alt p-3">
          <div className="mb-1 flex items-center justify-between gap-2">
            <span className="text-xs font-bold text-text-secondary">網址</span>
            <div className="flex shrink-0 gap-1">
              <Button variant="ghost" size="sm" onClick={onCopy} icon={<Copy className="h-3.5 w-3.5" aria-hidden="true" />}>
                複製
              </Button>
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex h-8 shrink-0 items-center justify-center gap-2 rounded-xl px-3 text-xs font-bold text-text-secondary transition-colors hover:bg-sand focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
              >
                <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                開啟
              </a>
            </div>
          </div>
          <p className="mb-3 break-all text-xs text-text-secondary">{item.url}</p>

          <p className="mb-1 text-xs font-bold text-text-secondary">說明</p>
          <p className="text-sm leading-relaxed whitespace-pre-line text-text-primary">
            {item.description || '（這支影片沒有說明）'}
          </p>
        </div>
      )}
    </Card>
  )
}
