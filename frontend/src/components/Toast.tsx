import { useCallback, useMemo, useState, type ReactNode } from 'react'
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

  // context value 一定要是穩定的物件，不能寫成 `value={{ show }}`。
  //
  // 每跳一則通知都會 setItems、讓這個 component 重繪，物件字面值就會換成新的
  // reference，所有 useToast() 的消費者跟著看到「toast 變了」。只要有任何一個
  // effect 把 toast 放進依賴陣列（VideosPage 就有），它就會被重跑——如果那個
  // effect 自己又會跳通知，就變成「跳通知 → 重繪 → 依賴變了 → 再跳通知」的
  // 無限迴圈，同一則訊息會把畫面疊滿。4 秒後自動消失的 setTimeout 同樣會
  // setItems，也會餵同一個迴圈。
  //
  // show 是 useCallback([]) 的常數，所以這個 useMemo 實際上永遠不會重算。
  const value = useMemo(() => ({ show }), [show])

  return (
    <ToastContext.Provider value={value}>
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
