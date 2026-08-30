import { DOC_TYPE_LABELS, type VideoDocument } from '../api/types'
import { formatTimestamp } from '../lib/format'
import { Badge } from './Badge'

/** 顯示 pipeline/document.py 整理出來的結構化文件。
 *
 * 刻意不引進 Markdown 函式庫：後端回的是結構化資料（章節／步驟／時間戳都是
 * 獨立欄位），直接用既有的排版元件畫就好，零新依賴。
 *
 * 給了 `onSeek` 時間戳就變成可點的按鈕（點了跳到影片那個時間點）；沒給就維持
 * 純文字標籤——不強迫每個呼叫端都要有播放器。 */
export function VideoDocumentView({
  document,
  onSeek,
}: {
  document: VideoDocument
  /** 點某個步驟的時間戳時呼叫，參數是該步驟的秒數。 */
  onSeek?: (sec: number) => void
}) {
  // 內容紀錄是「這支影片沒有可整理的流程」的退路，用不同的 badge 顏色跟
  // 真正的流程文件區分開，使用者才不會以為系統整理失敗了。
  const isFallback = document.doc_type === 'content_log'

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-base font-bold text-text-primary">{document.title}</h3>
        <Badge text={DOC_TYPE_LABELS[document.doc_type]} kind={isFallback ? 'neutral' : 'primary'} />
      </div>

      {/* 刻意不顯示 document.overview：它一稿兩用，內容就是面板上方那段摘要
          （後端 generate_document() 會把它寫進 videos.summary）。在這裡再印一次
          等於同一段文字出現兩遍，正是這次把摘要與文件合併時要消掉的重複。 */}

      {document.sections.map((section, si) => (
        <section key={si} className="space-y-2">
          <h4 className="border-b border-border pb-1 text-sm font-bold text-text-primary">
            {section.heading}
          </h4>
          <ol className="space-y-2">
            {section.steps.map((step, i) => (
              <li key={i} className="flex gap-3">
                {/* 時間戳固定寬度靠右，多個步驟的數字才會對齊成一直排。可點的
                    時候用 <button> 而不是加 onClick 的 <span>：鍵盤 Tab 得到、
                    Enter 觸發、螢幕閱讀器讀得出這是個按鈕。 */}
                {onSeek ? (
                  <button
                    type="button"
                    onClick={() => onSeek(step.timestamp_sec)}
                    // 帶上步驟標題：實測真實文件會有兩個步驟共用同一個時間戳
                    // （LLM 判定它們發生在同一秒），只講秒數的話螢幕閱讀器會聽到
                    // 兩個一模一樣的按鈕名稱，分不出是哪一步。
                    aria-label={`從 ${formatTimestamp(step.timestamp_sec)} 開始播放：${step.heading}`}
                    className={`${TIMESTAMP_CLASS} rounded text-primary hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary`}
                  >
                    {formatTimestamp(step.timestamp_sec)}
                  </button>
                ) : (
                  <span className={`${TIMESTAMP_CLASS} text-text-muted`}>
                    {formatTimestamp(step.timestamp_sec)}
                  </span>
                )}
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

/** 可點與不可點兩種時間戳共用的排版，差別只有顏色與互動狀態。 */
const TIMESTAMP_CLASS = 'w-12 shrink-0 pt-0.5 text-right font-mono text-xs'
