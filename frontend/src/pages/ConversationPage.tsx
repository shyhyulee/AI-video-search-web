import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { getStats, listVideos, sendConversationMessage, startConversation } from '../api/client'
import type { SearchResult, Video } from '../api/types'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { ChatBubble } from '../components/ChatBubble'
import { EmptyState } from '../components/EmptyState'
import { FilterChip } from '../components/FilterChip'
import { SearchResultCard } from '../components/SearchResultCard'
import { SearchScopeBar } from '../components/SearchScopeBar'
import { VideoPlayer } from '../components/VideoPlayer'
import { useSearchScope } from '../lib/useSearchScope'

const GREETING =
  '你好，跟我說說想找的影片內容，例如「找出有人進入生產線的畫面」。'

const SUGGESTED_PROMPTS = ['找出工廠中有人出現的片段', '找出全壘打畫面', '找出動物出現的片段']

const MODALITY_ORDER = ['字幕', '畫面', 'OCR'] as const

/** 從這一輪結果的 hit_source（例如「字幕＋畫面」「綜合」）彙整出這輪實際
 * 檢索到的模態，對齊文件「回答中標示已檢索哪些模態」。 */
function summarizeModalities(results: SearchResult[]): string {
  const found = new Set<string>()
  for (const r of results) {
    const parts = r.hit_source === '綜合' ? [...MODALITY_ORDER] : r.hit_source.split('＋')
    parts.forEach((p) => {
      if ((MODALITY_ORDER as readonly string[]).includes(p)) found.add(p)
    })
  }
  return MODALITY_ORDER.filter((m) => found.has(m)).join('、')
}

interface Message {
  speaker: 'user' | 'assistant'
  text: string
}

/** 後端的 LLM 可以在使用者勾選的範圍內「再收窄」（例如使用者說「只看第一支」）。
 * 收窄了就要講出來——畫面上的 chips 還是勾著 3 支、實際只搜了 1 支的話，使用者
 * 沒有任何線索可以理解結果為什麼變少。沒收窄就回傳空字串，不要每輪都加一句廢話。 */
function narrowedScopeNote(
  requested: number[],
  effective: number[],
  videos: Video[] | undefined,
): string {
  if (requested.length === 0 || effective.length === 0) return ''
  if (effective.length >= requested.length) return ''
  const titles = effective.map((id) => videos?.find((v) => v.id === id)?.title ?? `影片 #${id}`)
  return `｜這一輪只搜了：${titles.join('、')}`
}

/** 「對話搜尋」頁面，對齊 docs/10-web-ui-ux-warm-responsive-design.md
 * §6.4：桌機（≥900px）左右並排——左：對話訊息流；右：本輪結果與播放器
 * （播放器在上、結果清單在下，清單自己捲動）。≤900px 改回上下排列（對話在
 * 上、結果在下），對齊文件的響應式規則，也是這頁原本（Phase 1–4）的版面。
 * 第一名結果用大版型 Evidence Card，其餘刻意不做 search_tab 那個完整分數
 * 面板（Tkinter 版本身也沒有），重用簡化版播放器。 */
export function ConversationPage() {
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [messages, setMessages] = useState<Message[]>([{ speaker: 'assistant', text: GREETING }])
  const [input, setInput] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  const [statusText, setStatusText] = useState('')
  const transcriptRef = useRef<HTMLDivElement>(null)

  const { data: stats } = useQuery({ queryKey: ['stats'], queryFn: getStats })
  // 搜尋範圍跟「搜尋影片」頁共用同一份（在影片庫勾選），見 lib/useSearchScope.tsx。
  const { videoIds: scopeVideoIds } = useSearchScope()
  // 只為了把回報的範圍 id 換成標題。跟 LibraryPage／SearchScopeBar 同一個
  // query key，react-query 共用快取、不會多打一次 API。
  const { data: videos } = useQuery({ queryKey: ['videos', 'library'], queryFn: () => listVideos() })

  const startMutation = useMutation({ mutationFn: startConversation })

  useEffect(() => {
    startMutation.mutate(undefined, { onSuccess: (data) => setConversationId(data.id) })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 只在掛載時建立一次對話
  }, [])

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight })
  }, [messages])

  // 搜尋範圍隨參數帶進 mutate、不從 closure 讀（跟 SearchPage 同一個理由）。
  // 空陣列送 null：後端的 [] 是「限定了範圍但一支都沒選」，會回零筆。
  const sendMutation = useMutation({
    mutationFn: ({ message, videoIds }: { message: string; videoIds: number[] }) =>
      sendConversationMessage(
        conversationId as number,
        message,
        videoIds.length > 0 ? videoIds : null,
      ),
    onSuccess: (turn, variables) => {
      setMessages((prev) => [...prev, { speaker: 'assistant', text: turn.reply_text }])
      setResults(turn.results)
      setSelectedIndex(null)
      const modalities = summarizeModalities(turn.results)
      setStatusText(
        `花費 $${turn.cost_usd.toFixed(4)}` +
          (modalities ? `｜已檢索：${modalities}` : '') +
          narrowedScopeNote(variables.videoIds, turn.video_ids, videos),
      )
    },
    onError: (err: Error) => {
      setMessages((prev) => [...prev, { speaker: 'assistant', text: `處理時發生錯誤：${err.message}` }])
      setStatusText('發生錯誤')
    },
  })

  const sendMessage = (overrideText?: string) => {
    const message = (overrideText ?? input).trim()
    if (!message || conversationId === null || sendMutation.isPending) return
    setMessages((prev) => [...prev, { speaker: 'user', text: message }])
    setInput('')
    setStatusText('思考中…')
    sendMutation.mutate({ message, videoIds: scopeVideoIds })
  }

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    sendMessage()
  }

  const onComposerKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // 注音／拼音組字時按 Enter 是在選字，isComposing 為 true，這時不能送出，
    // 否則使用者選字會被誤判成送出訊息——全繁中介面特別容易踩到的 bug。
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      sendMessage()
    }
  }

  const selected = selectedIndex !== null ? results[selectedIndex] : null
  const showSuggestions = messages.length === 1

  return (
    <div className="flex h-full flex-col gap-4 md:min-h-0 md:flex-row">
      {/* 主從版面一律左右各半（md:w-1/2），跟影片庫／搜尋影片同一個比例，
          切換頁籤時分隔線不會左右跳動。改比例要三頁一起改。 */}
      <Card className="flex w-full min-w-0 max-h-[70vh] flex-col md:min-h-0 md:w-1/2 md:max-h-none">
        <div ref={transcriptRef} className="min-h-0 flex-1 space-y-3 overflow-auto">
          {messages.map((m, i) => (
            <ChatBubble key={i} speaker={m.speaker} text={m.text} />
          ))}
          {showSuggestions && (
            <div className="flex flex-wrap gap-2">
              {SUGGESTED_PROMPTS.map((prompt) => (
                <FilterChip key={prompt} label={prompt} onClick={() => sendMessage(prompt)} />
              ))}
            </div>
          )}
        </div>
        {/* 跟「搜尋影片」頁共用同一份範圍，所以這裡也要看得到、也能移除。 */}
        <SearchScopeBar className="mt-2" />
        <p className="mt-2 text-xs text-text-muted">
          {stats
            ? stats.analyzed_count > 0
              ? `已連接 ${stats.analyzed_count} 支影片索引`
              : '尚未有已分析完成的影片，先在「影片與分析」頁籤加入並分析影片'
            : ' '}
        </p>
        <form onSubmit={onSubmit} className="mt-1 flex shrink-0 items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onComposerKeyDown}
            disabled={conversationId === null || sendMutation.isPending}
            rows={2}
            placeholder="輸入想找的內容，Enter 送出、Shift+Enter 換行"
            className="flex-1 resize-none rounded-xl border border-border bg-card px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-primary focus:outline-none disabled:opacity-60"
          />
          <Button type="submit" variant="primary" disabled={conversationId === null || sendMutation.isPending}>
            送出
          </Button>
        </form>
        {statusText && (
          <p className="mt-1 text-sm text-text-secondary" aria-live="polite">
            {statusText}
          </p>
        )}
      </Card>

      <div className="flex w-full min-w-0 flex-col gap-4 md:min-h-0 md:w-1/2">
        <Card className="w-full">
          {selected ? (
            <VideoPlayer videoId={selected.video_id} startSec={selected.start_sec} title={selected.video_title} />
          ) : (
            <EmptyState title="尚未選取片段" />
          )}
        </Card>

        <Card className="flex w-full flex-col md:min-h-0 md:flex-1">
          <h2 className="mb-3 text-base font-bold text-text-primary">這一輪的相關片段</h2>
          <div className="md:min-h-0 md:flex-1 md:overflow-auto">
            {results.length === 0 ? (
              <EmptyState title="尚無結果" hints={['開始對話以取得相關片段']} />
            ) : (
              results.map((r, index) => (
                <SearchResultCard
                  key={r.segment_id}
                  result={r}
                  rank={index + 1}
                  featured={index === 0}
                  selected={index === selectedIndex}
                  onSelect={() => setSelectedIndex(index)}
                />
              ))
            )}
          </div>
        </Card>
      </div>
    </div>
  )
}
