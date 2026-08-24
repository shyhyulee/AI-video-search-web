import { Search } from 'lucide-react'
import type { InputHTMLAttributes } from 'react'

type SearchFieldSize = 'md' | 'lg'

const SIZE_CLASS: Record<SearchFieldSize, string> = {
  md: 'h-10 pl-9 text-sm',
  lg: 'h-12 pl-10 text-base',
}
const ICON_SIZE_CLASS: Record<SearchFieldSize, string> = {
  md: 'h-4 w-4',
  lg: 'h-5 w-5',
}

interface SearchFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  containerClassName?: string
  size?: SearchFieldSize
}

/** 帶搜尋圖示的輸入框，取代各頁面各自手刻的 <input>。size 用 prop 而非
 * className 覆寫控制，避免同一個 height/text-size utility 在 class 字串
 * 裡出現兩次、順序不保證誰生效的問題。 */
export function SearchField({ containerClassName = '', className = '', size = 'md', ...props }: SearchFieldProps) {
  return (
    <div className={`relative flex-1 ${containerClassName}`}>
      <Search
        className={`pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted ${ICON_SIZE_CLASS[size]}`}
        aria-hidden="true"
      />
      <input
        className={`w-full rounded-xl border border-border bg-card pr-3 text-text-primary placeholder:text-text-muted focus:border-primary focus:outline-none ${SIZE_CLASS[size]} ${className}`}
        {...props}
      />
    </div>
  )
}
