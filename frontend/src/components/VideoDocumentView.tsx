import { DOC_TYPE_LABELS, type VideoDocument } from '../api/types'
import { Badge } from './Badge'

/** 顯示 pipeline/document.py 整理出來的結構化文件。
 *
 * 刻意不引進 Markdown 函式庫：後端回的是結構化資料（章節／步驟／時間戳都是
 * 獨立欄位），直接用既有的排版元件畫就好，零新依賴。時間戳目前是純文字標籤，
 * 「點時間戳跳到影片」需要這個面板有播放器，留待之後。
 */
export function VideoDocumentView({ document }: { document: VideoDocument }) {
  // 內容紀錄是「這支影片沒有可整理的流程」的退路，用不同的 badge 顏色跟
  // 真正的流程文件區分開，使用者才不會以為系統整理失敗了。
  const isFallback = document.doc_type === 'content_log'

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-base font-bold text-text-primary">{document.title}</h3>
        <Badge text={DOC_TYPE_LABELS[document.doc_type]} kind={isFallback ? 'neutral' : 'primary'} />
      </div>

      <p className="text-sm leading-relaxed text-text-secondary">{document.overview}</p>

      {document.sections.map((section, si) => (
        <section key={si} className="space-y-2">
          <h4 className="border-b border-border pb-1 text-sm font-bold text-text-primary">
            {section.heading}
          </h4>
          <ol className="space-y-2">
            {section.steps.map((step, i) => (
              <li key={i} className="flex gap-3">
                {/* 時間戳固定寬度靠右，多個步驟的數字才會對齊成一直排 */}
                <span className="w-12 shrink-0 pt-0.5 text-right font-mono text-xs text-text-muted">
                  {formatTimestamp(step.timestamp_sec)}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-bold text-text-primary">{step.heading}</p>
                  <p className="text-sm leading-relaxed text-text-secondary">{step.detail}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>
      ))}

      {document.uncovered.length > 0 && (
        <section className="rounded-xl bg-surface-alt p-3">
          {/* 明講「影片裡沒交代」而不是含糊帶過：這份文件會被當成參考資料看，
              哪些是影片有的、哪些要自己補，必須分得出來。 */}
          <h4 className="mb-1 text-sm font-bold text-text-primary">影片未涵蓋的部分</h4>
          <ul className="list-disc space-y-1 pl-5">
            {document.uncovered.map((item, i) => (
              <li key={i} className="text-sm leading-relaxed text-text-secondary">
                {item}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

function formatTimestamp(sec: number): string {
  const total = Math.round(sec)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}
