import { createContext, useContext } from 'react'

export type ToastKind = 'success' | 'error' | 'info'

export interface ToastContextValue {
  show: (message: string, kind?: ToastKind) => void
}

export const ToastContext = createContext<ToastContextValue | null>(null)

/** 讀取全域 Toast，必須在 components/Toast.tsx 的 ToastProvider 內使用。 */
export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast 必須在 ToastProvider 內使用')
  return ctx
}
