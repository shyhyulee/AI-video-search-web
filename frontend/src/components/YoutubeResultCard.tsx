import { useEffect, useId, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronUp, Copy, ExternalLink, ImageOff, ListPlus, Play, X } from 'lucide-react'
import { downloadYoutube } from '../api/client'
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
 * 換成 YouTube 內嵌播放器（不用離開這一頁確認影片內容），「加入待分析」把影片
 * 下載進來排進「影片與分析」頁的待分析清單，點「查看詳情」在卡片內就地展開
 * 網址與說明（不用 Modal，窄螢幕不會擋住畫面）。
 *
 * 這張卡片**只負責下載、不觸發分析**：分析要花錢、也需要挑選要不要跑，一律
 * 留在「影片與分析」頁由使用者勾選後統一送出，這頁維持「挑片」的單一職責。
 *
 * 展開／播放／下載狀態都放在卡片內部，多張可以同時進行；外層 grid 記得加
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

  // --- 加入待分析：只跑下載 job，下載完影片就落在「待分析」清單裡 ---
  const [downloadJobId, setDownloadJobId] = useState<number | null>(null)
  const [added, setAdded] = useState(false)
  const [failure, setFailure] = useState('')
  // downloadJob 是輪詢查詢，同一個終態會被讀到很多次；用 ref 記下已經處理過的
  // job id，確保收尾（invalidate＋toast）只做一次。
  const handledDownload = useRef<number | null>(null)

  const downloadJob = useJobPolling(downloadJobId).data

  const downloadMutation = useMutation({
    mutationFn: () => downloadYoutube(item.url),
    onSuccess: (job) => setDownloadJobId(job.id),
    // 用搜尋結果挑片很容易挑到已經下載過的，DUPLICATE_JOB 是常態不是意外，
    // 給一句看得懂的話，不要把後端的原始訊息直接丟出來。
    onError: (err: Error) =>
      setFailure(
        err instanceof ApiError && err.code === 'DUPLICATE_JOB'
          ? '這支影片已經在影片庫或下載中'
          : `下載失敗：${err.message}`,
      ),
  })

  useEffect(() => {
    if (!downloadJob || handledDownload.current === downloadJob.id) return
    if (downloadJob.status === 'completed') {
      handledDownload.current = downloadJob.id
      // 下載完成 = 影片已經以 pending 狀態進 DB，刷新「待分析影片」清單與
      // Header 統計卡；分析要不要跑、什麼時候跑，交給「影片與分析」頁決定。
      queryClient.invalidateQueries({ queryKey: ['videos', 'pending'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
      // oxlint-disable-next-line react/set-state-in-effect
      setAdded(true)
      toast.show(`已把「${item.title}」加入待分析清單`, 'success')
    } else if (downloadJob.status === 'failed') {
      handledDownload.current = downloadJob.id
      // 來源是輪詢查詢（外部系統）而非 DOM 事件，ref 已擋掉重複執行。
      // oxlint-disable-next-line react/set-state-in-effect
      setFailure(`下載失敗：${downloadJob.error_message ?? '未知錯誤'}`)
    }
    // toast／queryClient 每次 render 都是新物件，放進 deps 會讓 effect 每輪都跑；
    // 真正的觸發條件只有 downloadJob 的狀態變化。
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [downloadJob])

  const busy =
    downloadMutation.isPending || (downloadJob ? downloadJob.status === 'queued' || downloadJob.status === 'running' : false)

  const progressText = (() => {
    if (failure) return failure
    if (added) return '✓ 已加入「影片與分析」待分析清單'
    if (downloadMutation.isPending) return '準備下載…'
    if (busy) return downloadJob?.progress_message ?? '下載中…'
    return ''
  })()

  const onAddClicked = () => {
    setFailure('')
    handledDownload.current = null
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
              disabled={busy || added}
              onClick={onAddClicked}
              icon={<ListPlus className="h-4 w-4" aria-hidden="true" />}
            >
              {added ? '已加入' : '加入待分析'}
            </Button>
          </div>

          {(busy || progressText) && (
            <div>
              {busy && (
                <div className="mb-1 h-1.5 overflow-hidden rounded-full bg-sand">
                  <div
                    className="h-full bg-primary transition-all"
                    style={{ width: `${downloadJob?.progress_percent ?? 0}%` }}
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
