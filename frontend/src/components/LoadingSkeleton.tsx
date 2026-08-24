type SkeletonVariant = 'list-item' | 'card' | 'text-block'

interface LoadingSkeletonProps {
  variant: SkeletonVariant
  count?: number
}

const PULSE = 'animate-pulse motion-reduce:animate-none rounded bg-sand'

/** 載入中佔位骨架屏，取代「載入中就是空白或殘留舊資料」。 */
export function LoadingSkeleton({ variant, count = 1 }: LoadingSkeletonProps) {
  return (
    <div className="flex flex-col gap-2" aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonItem key={i} variant={variant} />
      ))}
    </div>
  )
}

function SkeletonItem({ variant }: { variant: SkeletonVariant }) {
  if (variant === 'list-item') {
    return (
      <div className="flex items-center gap-3 border-b border-border py-3">
        <div className={`h-12 w-20 shrink-0 ${PULSE}`} />
        <div className="flex flex-1 flex-col gap-2">
          <div className={`h-4 w-2/5 ${PULSE}`} />
          <div className={`h-3 w-1/5 ${PULSE}`} />
        </div>
      </div>
    )
  }
  if (variant === 'card') {
    return <div className={`h-40 w-full ${PULSE}`} />
  }
  return (
    <div className="flex flex-col gap-2">
      <div className={`h-3 w-full ${PULSE}`} />
      <div className={`h-3 w-4/5 ${PULSE}`} />
      <div className={`h-3 w-3/5 ${PULSE}`} />
    </div>
  )
}
