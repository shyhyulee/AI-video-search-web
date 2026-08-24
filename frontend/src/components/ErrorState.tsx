import { AlertCircle } from 'lucide-react'
import { Button } from './Button'

interface ErrorStateProps {
  title: string
  detail?: string
  onRetry?: () => void
}

/** 取代裸文字錯誤訊息的置中提示區塊，用於明確的失敗狀態（區別於 EmptyState）。 */
export function ErrorState({ title, detail, onRetry }: ErrorStateProps) {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="max-w-sm text-center">
        <AlertCircle className="mx-auto mb-2 h-8 w-8 text-error" aria-hidden="true" />
        <p className="mb-1 text-base font-semibold text-text-primary">{title}</p>
        {detail && <p className="text-sm text-text-secondary">{detail}</p>}
        {onRetry && (
          <Button variant="secondary" size="sm" onClick={onRetry} className="mt-3">
            重試
          </Button>
        )}
      </div>
    </div>
  )
}
