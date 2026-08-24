import { Search } from 'lucide-react'
import type { InputHTMLAttributes } from 'react'

interface SearchFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  containerClassName?: string
}

/** 帶搜尋圖示的輸入框，取代各頁面各自手刻的 <input>。 */
export function SearchField({ containerClassName = '', className = '', ...props }: SearchFieldProps) {
  return (
    <div className={`relative flex-1 ${containerClassName}`}>
      <Search
        className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted"
        aria-hidden="true"
      />
      <input
        className={`h-10 w-full rounded-xl border border-border bg-card pl-9 pr-3 text-sm text-text-primary placeholder:text-text-muted focus:border-primary focus:outline-none ${className}`}
        {...props}
      />
    </div>
  )
}
