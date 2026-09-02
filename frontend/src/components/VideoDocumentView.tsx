import { DOC_TYPE_LABELS, type VideoDocument } from '../api/types'
import { formatTimestamp } from '../lib/format'
import { Badge } from './Badge'

/** 顯示 pipeline/document.py 整理出來的結構化文件。
 *
 * 刻意不引進 Markdown 函式庫：後端回的是結構化資料（章節／步驟／時間戳都是
 * 獨立欄位），直接用既有的排版元件畫就好，零新依賴。
 *
 * 給了 `onSeek` 時間戳就變成可點的按鈕；沒給就維持純文字標籤——不強迫每個
 * 呼叫端都要有播放器。兩個呼叫端做的事不同：影片庫的詳細面板是「切進觀看
 * 模式」，觀看模式本身則是「就地 seek」，見 VideoWatchView。
 *
 * **超出影片長度的時間戳不給點**，理由見 OUT_OF_RANGE_TOLERANCE_SEC。 */
export function VideoDocumentView({
  document,
  durationSec,
  onSeek,
}: {
  document: VideoDocument
  /** 影片長度，用來判斷哪些時間戳對不上這支影片。null＝不知道，就不判斷。 */
  durationSec?: number | null
  /** 點某個步驟的時間戳時呼叫，參數是該步驟的秒數。 */
  onSeek?: (sec: number) => void
}) {
  // 內容紀錄是「這支影片沒有可整理的流程」的退路，用不同的 badge 顏色跟
  // 真正的流程文件區分開，使用者才不會以為系統整理失敗了。
  const isFallback = document.doc_type === 'content_log'

  const beyondEnd = (sec: number) =>
    durationSec != null && sec > durationSec + OUT_OF_RANGE_TOLERANCE_SEC
  const beyondCount = document.sections.reduce(
    (n, section) => n + section.steps.filter((s) => beyondEnd(s.timestamp_sec)).length,
    0,
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-base font-bold text-text-primary">{document.title}</h3>
        <Badge text={DOC_TYPE_LABELS[document.doc_type]} kind={isFallback ? 'neutral' : 'primary'} />
      </div>

      {/* 刻意不顯示 document.overview：它一稿兩用，內容就是面板上方那段摘要
          （後端 generate_document() 會把它寫進 videos.summary）。在這裡再印一次
          等於同一段文字出現兩遍，正是這次把摘要與文件合併時要消掉的重複。 */}

      {/* 用一句話講出來，而不是只靠 tooltip：滑鼠移過去才看得到的說明，等於
          只有已經起疑的人才會發現。 */}
      {beyondCount > 0 && (
        <p className="rounded-xl bg-badge-warning-bg px-3 py-2 text-xs leading-relaxed text-warning">
          有 {beyondCount} 個步驟的時間點超出影片長度（{formatTimestamp(durationSec ?? 0)}），
          已停用它們的播放連結。這通常代表模型在那幾步上寫出了影片裡沒有的內容，內容本身也請斟酌。
        </p>
      )}

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
                {onSeek && !beyondEnd(step.timestamp_sec) ? (
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
                ) : beyondEnd(step.timestamp_sec) ? (
                  // 用 disabled 的 <button> 而不是純文字：跟旁邊可點的時間戳
                  // 同一種外觀語言（只是變灰、加刪除線），使用者看得出「這裡
                  // 本來應該可以點」，而不是以為這一步比較不重要。
                  <button
                    type="button"
                    disabled
                    title={`這個時間點超出影片長度（${formatTimestamp(durationSec ?? 0)}），無法播放`}
                    aria-label={`${formatTimestamp(step.timestamp_sec)}：超出影片長度，無法播放`}
                    className={`${TIMESTAMP_CLASS} text-text-muted line-through decoration-text-muted`}
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

/** 三種時間戳（可點／超出影片長度／純文字）共用的排版，差別只有顏色與互動狀態。 */
const TIMESTAMP_CLASS = 'w-12 shrink-0 pt-0.5 text-right font-mono text-xs'

/** 判斷「超出影片長度」時容許的誤差（秒）。
 *
 * `videos.duration_sec` 是整數（yt-dlp 的 metadata 四捨五入過），真實長度可能
 * 比它多零點幾秒，嚴格比較會把剛好落在片尾的合法步驟誤判成超出。2 秒足夠吸收
 * 這個誤差，又不會放過真正的問題——實測 8 支文件裡有問題的 3 支，超出的幅度
 * 分別是 4 分 23 秒、2 分 52 秒、5 分 38 秒，全是分鐘級的，見
 * docs/04-known-limitations-and-open-items.md。 */
const OUT_OF_RANGE_TOLERANCE_SEC = 2
