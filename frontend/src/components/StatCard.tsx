interface StatCardProps {
  label: string
  value: string
  size?: 'default' | 'compact'
}

/** Header 右側的精簡指標卡：標籤字小、數值字大；compact 縮小字級供窄螢幕使用。 */
export function StatCard({ label, value, size = 'default' }: StatCardProps) {
  return (
    <div className="flex flex-col">
      <span className={`font-bold text-text-primary ${size === 'compact' ? 'text-sm' : 'text-lg'}`}>
        {value}
      </span>
      <span className="text-xs text-text-secondary">{label}</span>
    </div>
  )
}
