interface FilterChipProps {
  label: string
  active?: boolean
  count?: number
  onClick: () => void
}

/** 篩選用的 pill 按鈕；active 用陶土色底。也用於對話搜尋的建議提示（不傳 active）。 */
export function FilterChip({ label, active = false, count, onClick }: FilterChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`inline-flex h-10 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-4 text-sm font-bold transition-colors ${
        active ? 'bg-primary text-white' : 'border border-border bg-card text-text-primary hover:bg-sand'
      }`}
    >
      {label}
      {count !== undefined && <span className={active ? 'text-white/80' : 'text-text-muted'}>{count}</span>}
    </button>
  )
}
