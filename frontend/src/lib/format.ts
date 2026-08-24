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

const SCORE_NA = 'N/A'

export function formatScore(score: number | null): string {
  return score === null ? SCORE_NA : score.toFixed(2)
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

export function truncate(text: string, limit: number): string {
  const flat = text.replace(/\n/g, ' ')
  if (flat.length <= limit) return flat
  return `${flat.slice(0, limit - 1).trimEnd()}…`
}
