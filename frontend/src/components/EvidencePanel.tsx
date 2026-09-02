import type { SearchResult } from '../api/types'
import { formatTimeRange } from '../lib/format'
import { SimilarityBar } from './SimilarityBar'

interface EvidencePanelProps {
  result: SearchResult
}

/** 搜尋結果的證據面板：三模態分數與片段描述。
 * 對齊 docs/prompts/10-web-ui-ux-warm-responsive-design.md §6.3「Evidence Panel」。
 *
 * **「最終相似度」與「字幕內容」已移除**（2026-09-02，使用者要求）：前者就是下面
 * 三個模態分數取最高，多一條百分比條只是把同一個數字再講一次；後者在片段卡片上
 * 已經看得到，而且字幕是幻覺率最高的一欄（見 `docs/04-known-limitations-and-open-items.md`
 * 的 ASR 一節），放在「證據」面板裡容易被當成比實際更可信的依據。
 * `SearchResult.similarity`／`transcript` 兩個欄位仍在 API 回應裡，只是這裡不顯示。 */
export function EvidencePanel({ result }: EvidencePanelProps) {
  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-base font-bold text-text-primary">{result.video_title}</h3>
      <p className="text-sm text-text-secondary">{formatTimeRange(result.start_sec, result.end_sec)}</p>

      {/* 三個模態分數並排成一列方便互相比較。 */}
      <div className="grid grid-cols-3 gap-2 rounded-xl border border-border bg-surface-alt p-3">
        <ScoreCell label="字幕" score={result.transcript_score} />
        <ScoreCell label="畫面" score={result.visual_score} />
        <ScoreCell label="OCR" score={result.ocr_score} />
      </div>

      <div>
        <h4 className="mb-1 text-sm font-bold text-text-primary">片段描述</h4>
        <p className="text-sm leading-relaxed text-text-primary">{result.description || '（無畫面描述）'}</p>
      </div>
    </div>
  )
}

function ScoreCell({ label, score }: { label: string; score: number | null }) {
  return (
    <div className="min-w-0">
      <p className="mb-1 text-xs text-text-muted">{label}</p>
      <SimilarityBar ratio={score} />
    </div>
  )
}
