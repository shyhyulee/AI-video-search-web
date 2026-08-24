import type { SearchResult } from '../api/types'
import { formatScore, formatTimeRange } from '../lib/format'
import { SimilarityBar } from './SimilarityBar'

interface EvidencePanelProps {
  result: SearchResult
}

/** 搜尋結果的證據面板：最終相似度、三模態分數、命中原因、片段描述與字幕。
 * 對齊 docs/10-web-ui-ux-warm-responsive-design.md §6.3「Evidence Panel」。 */
export function EvidencePanel({ result }: EvidencePanelProps) {
  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-base font-bold text-text-primary">{result.video_title}</h3>
      <p className="text-sm text-text-secondary">{formatTimeRange(result.start_sec, result.end_sec)}</p>

      <div>
        <p className="mb-1 text-xs font-bold text-text-secondary">最終相似度</p>
        <SimilarityBar ratio={result.similarity} />
      </div>

      <div className="grid grid-cols-3 gap-2 rounded-xl border border-border bg-surface-alt p-3 text-center">
        <ScoreCell label="字幕" value={formatScore(result.transcript_score)} />
        <ScoreCell label="畫面" value={formatScore(result.visual_score)} />
        <ScoreCell label="OCR" value={formatScore(result.ocr_score)} />
      </div>

      <p className="text-sm text-text-secondary">
        主要命中來源：<span className="font-bold text-text-primary">{result.hit_source}</span>
      </p>
      <p className="text-xs text-text-muted">
        融合分數 {result.fusion_score.toFixed(3)}（排序依據）・{result.fusion_strategy}
      </p>

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

function ScoreCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-text-muted">{label}</p>
      <p className="text-sm font-bold text-text-primary">{value}</p>
    </div>
  )
}
