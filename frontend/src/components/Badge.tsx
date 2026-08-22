type BadgeKind = 'success' | 'warning' | 'error' | 'neutral' | 'primary'

const BG: Record<BadgeKind, string> = {
  success: 'bg-badge-success-bg text-success',
  warning: 'bg-badge-warning-bg text-warning',
  error: 'bg-badge-error-bg text-error',
  neutral: 'bg-badge-neutral-bg text-text-secondary',
  primary: 'bg-badge-primary-bg text-primary',
}

interface BadgeProps {
  text: string
  kind?: BadgeKind
}

/** 小型狀態標籤，底色＋文字辨識，不只靠顏色，對齊 ui/widgets.py 的 Badge。 */
export function Badge({ text, kind = 'neutral' }: BadgeProps) {
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-bold ${BG[kind]}`}>{text}</span>
  )
}
