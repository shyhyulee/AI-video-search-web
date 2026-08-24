import type { ReactNode } from 'react'

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
  icon?: ReactNode
}

/** 小型狀態標籤，底色＋文字辨識，不只靠顏色，pill 圓角。 */
export function Badge({ text, kind = 'neutral', icon }: BadgeProps) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-bold ${BG[kind]}`}>
      {icon}
      {text}
    </span>
  )
}
