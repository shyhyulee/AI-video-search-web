interface StatCardProps {
  label: string
  value: string
}

/** Header 右側的精簡指標卡：標籤字小、數值字大，對齊 ui/widgets.py 的 StatCard。 */
export function StatCard({ label, value }: StatCardProps) {
  return (
    <div className="flex flex-col">
      <span className="text-lg font-bold text-text-primary">{value}</span>
      <span className="text-xs text-text-secondary">{label}</span>
    </div>
  )
}
