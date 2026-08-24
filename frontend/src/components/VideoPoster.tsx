import { useState } from 'react'
import { ImageOff } from 'lucide-react'
import { getThumbnailUrl } from '../api/client'

type PosterSize = 'sm' | 'lg'

const SIZE_CLASS: Record<PosterSize, string> = {
  sm: 'h-12 w-20',
  lg: 'h-[180px] w-[320px]',
}

interface VideoPosterProps {
  videoId: number
  size?: PosterSize
  className?: string
}

/** 影片縮圖；縮圖產生失敗時（檔案遺失、ffmpeg 逾時）顯示圖示佔位，不留空白。 */
export function VideoPoster({ videoId, size = 'lg', className = '' }: VideoPosterProps) {
  const [failed, setFailed] = useState(false)

  if (failed) {
    return (
      <div
        className={`flex shrink-0 items-center justify-center rounded-xl bg-sand text-text-muted ${SIZE_CLASS[size]} ${className}`}
      >
        <ImageOff className={size === 'sm' ? 'h-4 w-4' : 'h-6 w-6'} aria-hidden="true" />
      </div>
    )
  }

  return (
    <img
      src={getThumbnailUrl(videoId)}
      alt=""
      className={`shrink-0 rounded-xl bg-sand object-cover ${SIZE_CLASS[size]} ${className}`}
      onError={() => setFailed(true)}
    />
  )
}
