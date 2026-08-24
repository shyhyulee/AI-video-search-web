import type { ReactNode } from 'react'

interface EmptyStateProps {
  title: string
  hints?: string[]
  icon?: ReactNode
}

/** 取代空表格的置中提示區塊。 */
export function EmptyState({ title, hints = [], icon }: EmptyStateProps) {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="max-w-sm text-center">
        {icon && <div className="mx-auto mb-2 text-text-muted">{icon}</div>}
        <p className="mb-2 text-base font-semibold text-text-primary">{title}</p>
        {hints.map((line) => (
          <p key={line} className="text-sm text-text-secondary">
            {line}
          </p>
        ))}
      </div>
    </div>
  )
}
