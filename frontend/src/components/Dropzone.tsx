import { useRef, useState, type DragEvent } from 'react'
import { UploadCloud } from 'lucide-react'

interface DropzoneProps {
  onFileSelected: (file: File) => void
  accept?: string
  disabled?: boolean
  hint?: string
}

/** 點擊或拖放選擇本機檔案；實際上傳邏輯（XHR 進度）留在呼叫端處理。 */
export function Dropzone({ onFileSelected, accept = '.mp4,.mov,.mkv,.webm', disabled = false, hint }: DropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)

  const openPicker = () => {
    if (!disabled) inputRef.current?.click()
  }

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragOver(false)
    if (disabled) return
    const file = e.dataTransfer.files?.[0]
    if (file) onFileSelected(file)
  }

  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-disabled={disabled}
      onClick={openPicker}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          openPicker()
        }
      }}
      onDragOver={(e) => {
        e.preventDefault()
        if (!disabled) setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
      className={`flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl border-2 border-dashed px-4 py-6 text-center transition-colors ${
        disabled
          ? 'cursor-not-allowed border-border bg-sand/50 text-text-muted'
          : dragOver
            ? 'border-primary bg-primary-soft'
            : 'border-border bg-card hover:border-primary hover:bg-sand'
      }`}
    >
      <UploadCloud className="h-6 w-6 text-text-muted" aria-hidden="true" />
      <p className="text-sm font-bold text-text-primary">點擊或拖放本機影片到這裡</p>
      {hint && <p className="text-xs text-text-secondary">{hint}</p>}
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        disabled={disabled}
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onFileSelected(file)
          e.target.value = ''
        }}
      />
    </div>
  )
}
