import { useCallback, useState, type ReactNode } from 'react'
import { ToastContext, type ToastKind } from '../lib/useToast'

interface ToastItem {
  id: number
  message: string
  kind: ToastKind
}

const KIND_CLASS: Record<ToastKind, string> = {
  success: 'border-success bg-success-soft text-text-primary',
  error: 'border-error bg-badge-error-bg text-text-primary',
  info: 'border-border bg-card text-text-primary',
}

let nextToastId = 0

/** 全域 Toast，掛在 App 層級一次；用 useToast() 觸發，約 4 秒自動消失。
 * role="status"/"alert" 讓每則訊息各自成為 live region，比在外層包一個
 * aria-live 容器更符合動態新增項目的標準做法。 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])

  const show = useCallback((message: string, kind: ToastKind = 'info') => {
    const id = nextToastId++
    setItems((prev) => [...prev, { id, message, kind }])
    setTimeout(() => {
      setItems((prev) => prev.filter((item) => item.id !== id))
    }, 4000)
  }, [])

  return (
    <ToastContext.Provider value={{ show }}>
      {children}
      <div className="fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 flex-col gap-2">
        {items.map((item) => (
          <div
            key={item.id}
            role={item.kind === 'error' ? 'alert' : 'status'}
            className={`rounded-xl border px-4 py-2 text-sm shadow-card ${KIND_CLASS[item.kind]}`}
          >
            {item.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
