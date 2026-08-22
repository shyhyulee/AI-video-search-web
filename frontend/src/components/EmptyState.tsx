interface EmptyStateProps {
  title: string
  hints?: string[]
}

/** 取代空表格的置中提示區塊，對齊 ui/widgets.py 的 EmptyState。 */
export function EmptyState({ title, hints = [] }: EmptyStateProps) {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center">
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
