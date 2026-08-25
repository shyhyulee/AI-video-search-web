import { useId, useState } from 'react'
import { ChevronDown, ChevronUp, Copy, ExternalLink, ImageOff } from 'lucide-react'
import type { YoutubeSearchItem } from '../api/types'
import { formatDuration, formatViewCount } from '../lib/format'
import { Button } from './Button'
import { Card } from './Card'
import { useToast } from '../lib/useToast'

interface YoutubeResultCardProps {
  item: YoutubeSearchItem
}

/** YouTube 搜尋結果卡片：收合時只有縮圖／標題／頻道資訊，點「查看詳情」
 * 在卡片內就地展開網址與說明（不用 Modal，窄螢幕不會擋住畫面）。展開狀態
 * 放在卡片內部，多張可以同時展開；外層 grid 記得加 items-start，不然展開
 * 一張會把同一列其他卡片一起撐高。 */
export function YoutubeResultCard({ item }: YoutubeResultCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [thumbnailFailed, setThumbnailFailed] = useState(false)
  const toast = useToast()
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

  return (
    <Card padding="none" elevated className="flex flex-col overflow-hidden">
      {item.thumbnail_url && !thumbnailFailed ? (
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
        <Button
          variant="secondary"
          size="sm"
          className="mt-auto w-full"
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
