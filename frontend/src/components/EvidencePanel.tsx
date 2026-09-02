import type { SearchResult } from '../api/types'
import { formatTimeRange } from '../lib/format'
import { SimilarityBar } from './SimilarityBar'

interface EvidencePanelProps {
  result: SearchResult
}

/** 搜尋結果的證據面板：最終相似度、三模態分數、片段描述與字幕。
 * 對齊 docs/prompts/10-web-ui-ux-warm-responsive-design.md §6.3「Evidence Panel」。 */
export function EvidencePanel({ result }: EvidencePanelProps) {
  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-base font-bold text-text-primary">{result.video_title}</h3>
      <p className="text-sm text-text-secondary">{formatTimeRange(result.start_sec, result.end_sec)}</p>

      <div>
        <p className="mb-1 text-xs font-bold text-text-secondary">最終相似度</p>
        <SimilarityBar ratio={result.similarity} />
      </div>

      {/* 三個模態分數跟「最終相似度」同一種百分比條（最終相似度就是三者取最高
          分），並排成一列方便互相比較。 */}
      <div className="grid grid-cols-3 gap-2 rounded-xl border border-border bg-surface-alt p-3">
        <ScoreCell label="字幕" score={result.transcript_score} />
        <ScoreCell label="畫面" score={result.visual_score} />
        <ScoreCell label="OCR" score={result.ocr_score} />
      </div>

      <div>
        <h4 className="mb-1 text-sm font-bold text-text-primary">片段描述</h4>
        <p className="text-sm leading-relaxed text-text-primary">{result.description || '（無畫面描述）'}</p>
      </div>
      <div>
        <h4 className="mb-1 text-sm font-bold text-text-primary">字幕內容</h4>
        <p className="text-sm leading-relaxed text-text-secondary">{result.transcript || '（此片段無字幕）'}</p>
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
