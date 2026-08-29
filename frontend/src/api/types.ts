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
  /** 整理過的文件類型；null＝還沒整理過。清單刻意只帶類型不帶內容，
   * 完整文件走 getVideoDocument()。 */
  document_type: DocumentType | null
  has_transcript: boolean
  has_visual: boolean
  has_ocr: boolean
}

export type DocumentType = 'sop' | 'tutorial' | 'lecture_notes' | 'content_log'

/** 對齊 pipeline/document.py 的 DOC_TYPE_LABELS。 */
export const DOC_TYPE_LABELS: Record<DocumentType, string> = {
  sop: '流程 SOP',
  tutorial: '教學步驟',
  lecture_notes: '課堂筆記',
  content_log: '內容紀錄',
}

export interface DocumentStep {
  timestamp_sec: number
  heading: string
  detail: string
}

export interface DocumentSection {
  heading: string
  steps: DocumentStep[]
}

export interface VideoDocument {
  doc_type: DocumentType
  title: string
  overview: string
  sections: DocumentSection[]
  /** 素材裡沒交代清楚、讀者要自己補的事。可以是空陣列。 */
  uncovered: string[]
}

export interface VideoDocumentResponse {
  video_id: number
  document: VideoDocument
  model: string | null
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
