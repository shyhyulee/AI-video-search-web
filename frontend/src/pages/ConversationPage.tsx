import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { getStats, sendConversationMessage, startConversation } from '../api/client'
import type { SearchResult } from '../api/types'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { ChatBubble } from '../components/ChatBubble'
import { EmptyState } from '../components/EmptyState'
import { FilterChip } from '../components/FilterChip'
import { SearchResultCard } from '../components/SearchResultCard'
import { VideoPlayer } from '../components/VideoPlayer'

const GREETING =
  '你好，跟我說說想找的影片內容，例如「找出有人進入生產線的畫面」。之後可以接著說「只看穿紅色衣服的人」或「播放第二段」。'

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

/** 「對話搜尋」頁面，對齊 ui/conversation_tab.py：訊息串 + 這一輪的相關
 * 片段，見 docs/07-ui-structure-and-features.md 6.4 節與
 * docs/10-web-ui-ux-warm-responsive-design.md §6.4。第一名結果用大版型
 * Evidence Card，其餘刻意不做 search_tab 那個完整分數面板（Tkinter 版
 * 本身也沒有），重用簡化版播放器。 */
export function ConversationPage() {
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [messages, setMessages] = useState<Message[]>([{ speaker: 'assistant', text: GREETING }])
  const [input, setInput] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  const [statusText, setStatusText] = useState('')
  const transcriptRef = useRef<HTMLDivElement>(null)

  const { data: stats } = useQuery({ queryKey: ['stats'], queryFn: getStats })

  const startMutation = useMutation({ mutationFn: startConversation })

  useEffect(() => {
    startMutation.mutate(undefined, { onSuccess: (data) => setConversationId(data.id) })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 只在掛載時建立一次對話
  }, [])

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight })
  }, [messages])

  const sendMutation = useMutation({
    mutationFn: (message: string) => sendConversationMessage(conversationId as number, message),
    onSuccess: (turn) => {
      setMessages((prev) => [...prev, { speaker: 'assistant', text: turn.reply_text }])
      setResults(turn.results)
      setSelectedIndex(null)
      const modalities = summarizeModalities(turn.results)
      setStatusText(`花費 $${turn.cost_usd.toFixed(4)}${modalities ? `｜已檢索：${modalities}` : ''}`)
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
    sendMutation.mutate(message)
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
    <div className="flex h-full flex-col gap-4">
      <Card className="flex max-h-[70vh] flex-col md:h-3/5 md:max-h-none">
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

      <div className="flex flex-col gap-4 md:min-h-0 md:flex-1 md:flex-row">
        <Card className="flex w-full flex-col md:min-h-0 md:w-3/5">
          <h2 className="mb-3 text-base font-bold text-text-primary">這一輪的相關片段</h2>
          <div className="md:min-h-0 md:flex-1 md:overflow-auto">
            {results.length === 0 ? (
              <EmptyState title="尚無結果" hints={['在上方輸入想找的內容開始對話']} />
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

        <Card className="w-full md:min-h-0 md:w-2/5 md:overflow-auto">
          {selected ? (
            <VideoPlayer videoId={selected.video_id} startSec={selected.start_sec} title={selected.video_title} />
          ) : (
            <EmptyState title="點選左方片段即可播放" />
          )}
        </Card>
      </div>
    </div>
  )
}
