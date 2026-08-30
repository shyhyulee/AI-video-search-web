// 對齊 src/ai_video_search_web/ui/widgets.py 的格式化函式，維持跟 Tkinter
// 版一致的顯示格式。

export function formatDuration(seconds: number | null): string {
  if (!seconds) return '--:--'
  const total = Math.round(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h) {
    return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  }
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export function formatDateTime(isoStr: string | null): string {
  if (!isoStr) return '--'
  const date = new Date(isoStr)
  if (Number.isNaN(date.getTime())) return isoStr
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}/${pad(date.getMonth() + 1)}/${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** 秒數轉 `MM:SS`。影片文件的步驟時間戳、以及點它之後播放器旁的標示共用同一個
 * 格式；超過 60 分鐘不進位成 HH:MM:SS（分析長度上限就是 1 小時）。
 *
 * 註：`formatTimeRange()` 裡還有一份一模一樣的 inline `mmss`，那是既有的，
 * 跟這次的功能無關，沒有一起動。 */
export function formatTimestamp(sec: number): string {
  const total = Math.round(sec)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export function formatTimeRange(startSec: number, endSec: number): string {
  const mmss = (sec: number) => {
    const total = Math.round(sec)
    const m = Math.floor(total / 60)
    const s = total % 60
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  }
  return `${mmss(startSec)}–${mmss(endSec)}`
}

export function formatCost(usd: number | null): string {
  return `US$${(usd ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function formatPercent(ratio: number): string {
  return `${Math.round(ratio * 100)}%`
}

export function formatElapsed(startedAt: string | null): string {
  if (!startedAt) return '0:00'
  const startMs = new Date(startedAt).getTime()
  if (Number.isNaN(startMs)) return '0:00'
  const elapsedSec = Math.max(0, Math.floor((Date.now() - startMs) / 1000))
  const m = Math.floor(elapsedSec / 60)
  const s = elapsedSec % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

/** 觀看數用中文的萬／億進位（對齊 YouTube 中文介面：9,876 / 1.2萬 / 728萬）。 */
export function formatViewCount(count: number | null): string {
  if (count === null) return '--'
  const scale = (value: number, unit: string) =>
    `${value < 10 ? value.toFixed(1) : String(Math.round(value))}${unit}`
  if (count >= 100_000_000) return scale(count / 100_000_000, '億')
  if (count >= 10_000) return scale(count / 10_000, '萬')
  return count.toLocaleString('en-US')
}

export function truncate(text: string, limit: number): string {
  const flat = text.replace(/\n/g, ' ')
  if (flat.length <= limit) return flat
  return `${flat.slice(0, limit - 1).trimEnd()}…`
}
