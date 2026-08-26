import type {
  ApiErrorBody,
  ConversationTurn,
  HeaderStats,
  Job,
  SearchResponse,
  Video,
  YoutubeSearchResponse,
} from './types'
import { ApiError } from './types'

// 開發時走 vite.config.ts 的 proxy（/api -> 127.0.0.1:8000），瀏覽器端看到的
// 是相對路徑、同源，不需要 CORS；後端的 CORSMiddleware 是給非 proxy 場景
// （例如未來獨立部署）用的保險，見 docs/09-web-ui-migration-plan.md。
const BASE = '/api/v1'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: init?.body && !(init.body instanceof FormData) ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  })
  if (!resp.ok) {
    const body = (await resp.json()) as ApiErrorBody
    throw new ApiError(resp.status, body)
  }
  if (resp.status === 204) {
    return undefined as T
  }
  return (await resp.json()) as T
}

export function getStats(): Promise<HeaderStats> {
  return request<HeaderStats>('/stats')
}

export function listVideos(status?: 'pending'): Promise<Video[]> {
  const query = status ? `?status=${status}` : ''
  return request<Video[]>(`/videos${query}`)
}

export function getVideo(videoId: number): Promise<Video> {
  return request<Video>(`/videos/${videoId}`)
}

export function deleteVideo(videoId: number): Promise<void> {
  return request<void>(`/videos/${videoId}`, { method: 'DELETE' })
}

export function downloadYoutube(url: string): Promise<Job> {
  return request<Job>('/videos/youtube', {
    method: 'POST',
    body: JSON.stringify({ url }),
  })
}

export function analyzeVideo(videoId: number): Promise<Job> {
  return request<Job>(`/videos/${videoId}/analyze`, { method: 'POST' })
}

export function reanalyzeVideo(videoId: number): Promise<Job> {
  return request<Job>(`/videos/${videoId}/reanalyze`, { method: 'POST' })
}

export function regenerateSummary(videoId: number): Promise<Video> {
  return request<Video>(`/videos/${videoId}/summary`, { method: 'POST' })
}

export function getStreamUrl(videoId: number): string {
  return `${BASE}/videos/${videoId}/stream`
}

export function getThumbnailUrl(videoId: number): string {
  return `${BASE}/videos/${videoId}/thumbnail`
}

// 本機上傳（`uploadVideo()`，XHR + onProgress）在移除「影片與分析」頁的新增
// 影片區塊時一併刪掉，見 docs/11 §8.5。後端 `POST /videos/upload` 仍在、測試
// 也還在，之後要恢復的話是加回一個前端函式的事。

export function listJobs(videoId?: number): Promise<Job[]> {
  const query = videoId !== undefined ? `?video_id=${videoId}` : ''
  return request<Job[]>(`/jobs${query}`)
}

export function getJob(jobId: number): Promise<Job> {
  return request<Job>(`/jobs/${jobId}`)
}

export function retryJob(jobId: number): Promise<Job> {
  return request<Job>(`/jobs/${jobId}/retry`, { method: 'POST' })
}

export interface SearchParams {
  query: string
  video_id?: number | null
  top_k?: number
}

export function search(params: SearchParams): Promise<SearchResponse> {
  return request<SearchResponse>('/search', { method: 'POST', body: JSON.stringify(params) })
}

/** 搜尋 YouTube 影片（只查 metadata，不會下載任何東西）。 */
export function searchYoutube(query: string, limit?: number): Promise<YoutubeSearchResponse> {
  const params = new URLSearchParams({ q: query })
  if (limit !== undefined) params.set('limit', String(limit))
  return request<YoutubeSearchResponse>(`/youtube/search?${params}`)
}

export function startConversation(): Promise<{ id: number }> {
  return request<{ id: number }>('/conversations', { method: 'POST' })
}

export function getConversation(conversationId: number): Promise<ConversationTurn> {
  return request<ConversationTurn>(`/conversations/${conversationId}`)
}

export function sendConversationMessage(conversationId: number, message: string): Promise<ConversationTurn> {
  return request<ConversationTurn>(`/conversations/${conversationId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ message }),
  })
}
