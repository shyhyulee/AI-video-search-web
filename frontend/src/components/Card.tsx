import type { HTMLAttributes } from 'react'

const PADDING_CLASS = { none: '', sm: 'p-3', md: 'p-4', lg: 'p-6' } as const

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  padding?: keyof typeof PADDING_CLASS
  elevated?: boolean
}

/** 共用卡片容器；陰影只在 elevated 時套用，對齊文件「陰影只用於浮起的主要卡片」。 */
export function Card({ padding = 'md', elevated = false, className = '', children, ...props }: CardProps) {
  return (
    <div
      className={`rounded-card border border-border bg-card ${PADDING_CLASS[padding]} ${elevated ? 'shadow-card' : ''} ${className}`}
      {...props}
    >
      {children}
    </div>
  )
}
