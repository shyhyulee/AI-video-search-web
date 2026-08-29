import type {
  ApiErrorBody,
  ConversationTurn,
  HeaderStats,
  Job,
  SearchResponse,
  Video,
  VideoDocumentResponse,
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

// `regenerateSummary()`（POST /videos/{id}/summary）在把「摘要」與「整理成文件」
// 合併成一顆按鈕時刪掉：摘要現在由 generateVideoDocument() 一併產出。後端端點與
// 測試仍在（analyzer 的自動摘要也還在用 pipeline/summary.py），要恢復的話是加回
// 一個前端函式的事——跟 uploadVideo() 同樣的處理方式。

/** 把整支影片整理成一份結構化文件。同步端點、會呼叫 LLM，比其他 POST 慢
 * 得多（輸出 token 比摘要多一個量級），呼叫端要有明確的等待狀態。 */
export function generateVideoDocument(videoId: number): Promise<VideoDocumentResponse> {
  return request<VideoDocumentResponse>(`/videos/${videoId}/document`, { method: 'POST' })
}

/** 讀回已整理的文件。還沒整理過時後端回 404（正常狀態，不是錯誤），
 * 呼叫端要自己接住。 */
export function getVideoDocument(videoId: number): Promise<VideoDocumentResponse> {
  return request<VideoDocumentResponse>(`/videos/${videoId}/document`)
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

/** 還沒到終態（queued／running）的工作。「影片與分析」頁靠它在重新整理後把
 * 進行中的分析接回進度顯示——追蹤清單本身只活在 React state，F5 就沒了。 */
export function listActiveJobs(jobType?: 'analysis' | 'download'): Promise<Job[]> {
  const query = jobType ? `?active=true&job_type=${jobType}` : '?active=true'
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
  /** 搜尋範圍：省略／null 代表搜全部影片，給一組 id 就只搜那幾支。單支影片
   * 送長度 1 的陣列即可，後端沒有另外的單數欄位。 */
  video_ids?: number[] | null
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

/** videoIds 是畫面上勾選的搜尋範圍，每輪都要重送——後端刻意不把它存進
 * conversations 表（範圍屬於「使用者現在看的畫面」，不是對話內容的一部分）。 */
export function sendConversationMessage(
  conversationId: number,
  message: string,
  videoIds?: number[] | null,
): Promise<ConversationTurn> {
  return request<ConversationTurn>(`/conversations/${conversationId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ message, video_ids: videoIds ?? null }),
  })
}
