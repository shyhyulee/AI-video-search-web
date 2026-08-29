// 對齊 src/ai_video_search_web/schemas/*.py 的 Pydantic model 欄位，
// 見 docs/09-web-ui-migration-plan.md。改後端 schema 時要同步改這裡。

export interface HeaderStats {
  pending_count: number
  analyzed_count: number
  segment_count: number
  total_cost_usd: number
}

export type VideoStatus = 'pending' | 'analyzing' | 'analyzed' | 'failed'
export type VideoSource = 'youtube' | 'local'

export interface Video {
  id: number
  title: string
  source: VideoSource
  source_url: string | null
  duration_sec: number | null
  status: VideoStatus
  pipeline_stage: string | null
  created_at: string
  analyzed_at: string | null
  segment_count: number | null
  cost_usd: number | null
  summary: string | null
  has_transcript: boolean
  has_visual: boolean
  has_ocr: boolean
}

export type JobType = 'download' | 'analysis'
export type JobStatus = 'queued' | 'running' | 'completed' | 'failed'

export interface Job {
  id: number
  job_type: JobType
  video_id: number | null
  status: JobStatus
  stage: string | null
  progress_percent: number | null
  progress_message: string | null
  error_message: string | null
  cost_usd: number | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface SearchResult {
  segment_id: number
  video_id: number
  video_title: string
  start_sec: number
  end_sec: number
  similarity: number
  hit_source: string
  description: string
  transcript: string | null
  transcript_score: number | null
  visual_score: number | null
  ocr_score: number | null
  fusion_strategy: string
  fusion_score: number
}

export interface SearchResponse {
  results: SearchResult[]
  cost_usd: number
  is_confident: boolean
}

export interface YoutubeSearchItem {
  video_id: string
  title: string
  url: string
  /** YouTube 搜尋結果自帶的說明摘要，約 100 字後由 YouTube 自己截斷成 `...`，
   * 不是完整說明；要完整說明得對單支影片再打一次 yt-dlp（約 3.6 秒），
   * 目前刻意不做。 */
  description: string
  duration_sec: number | null
  channel: string
  view_count: number | null
  thumbnail_url: string | null
}

export interface YoutubeSearchResponse {
  items: YoutubeSearchItem[]
}

export interface ConversationTurn {
  reply_text: string
  results: SearchResult[]
  cost_usd: number
  /** 這一輪實際生效的搜尋範圍（空陣列＝全部影片）。可能比畫面上勾選的更窄——
   * 後端的 LLM 會在勾選範圍內再收窄，見 pipeline/conversation._resolve_video_ids()。 */
  video_ids: number[]
}

// 沿用 docs/08-web-ui-migration-design.md 第 6 節的 Error Schema，
// api/errors.py 實作。
export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details: Record<string, unknown> | null
  }
}

export class ApiError extends Error {
  code: string
  status: number

  constructor(status: number, body: ApiErrorBody) {
    super(body.error.message)
    this.name = 'ApiError'
    this.code = body.error.code
    this.status = status
  }
}
