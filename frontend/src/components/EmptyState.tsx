import type { ReactNode } from 'react'

interface EmptyStateProps {
  title: string
  hints?: string[]
  icon?: ReactNode
  /** 選填的行動點（按鈕或連結）。用在「這個空狀態要靠別的頁面才能解掉」的
   * 情境，例如待分析清單空了要去「新增影片」頁加影片。 */
  action?: ReactNode
}

/** 取代空表格的置中提示區塊。 */
export function EmptyState({ title, hints = [], icon, action }: EmptyStateProps) {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="max-w-sm text-center">
        {icon && <div className="mb-2 flex justify-center text-text-muted">{icon}</div>}
        <p className="mb-2 text-base font-semibold text-text-primary">{title}</p>
        {hints.map((line) => (
          <p key={line} className="text-sm text-text-secondary">
            {line}
          </p>
        ))}
        {action && <div className="mt-3 flex justify-center">{action}</div>}
      </div>
    </div>
  )
}
