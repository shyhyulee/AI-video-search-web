import * as Dialog from '@radix-ui/react-dialog'
import { Button } from './Button'

interface ConfirmDialogProps {
  open: boolean
  title: string
  description?: string
  confirmLabel?: string
  cancelLabel?: string
  destructive?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** 取代 window.confirm；focus trap／Escape／關閉後焦點還原交給 Radix Dialog 處理。 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = '確認',
  cancelLabel = '取消',
  destructive = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  // Radix 在沒有 Dialog.Description 時會在 console 印無障礙警告，
  // 沒有 description 時明確傳 aria-describedby=undefined 抑制。
  const descriptionProps = description ? {} : { 'aria-describedby': undefined }

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel()
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-text-primary/40" />
        <Dialog.Content
          {...descriptionProps}
          className="fixed left-1/2 top-1/2 z-50 w-[min(420px,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-card bg-card p-6 shadow-card focus:outline-none"
          onEscapeKeyDown={onCancel}
        >
          <Dialog.Title className="text-base font-bold text-text-primary">{title}</Dialog.Title>
          {description && (
            <Dialog.Description className="mt-2 text-sm text-text-secondary">
              {description}
            </Dialog.Description>
          )}
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="secondary" onClick={onCancel}>
              {cancelLabel}
            </Button>
            <Button variant={destructive ? 'danger' : 'primary'} onClick={onConfirm}>
              {confirmLabel}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
