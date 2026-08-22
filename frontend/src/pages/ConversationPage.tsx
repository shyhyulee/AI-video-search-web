import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { getStreamUrl, sendConversationMessage, startConversation } from '../api/client'
import type { SearchResult } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { formatPercent, formatTimeRange, truncate } from '../lib/format'

const GREETING = '你好，跟我說說想找的影片內容，例如「找出有人進入生產線的畫面」。之後可以接著說「只看穿紅色衣服的人」或「播放第二段」。'

interface Message {
  speaker: '你' | '助理'
  text: string
}

/** 「對話搜尋」頁面，對齊 ui/conversation_tab.py：訊息串 + 這一輪的相關
 * 片段，見 docs/07-ui-structure-and-features.md 6.4 節。刻意不做
 * search_tab 那個完整分數面板（Tkinter 版本身也沒有），重用簡化版播放器。
 */
export function ConversationPage() {
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [messages, setMessages] = useState<Message[]>([{ speaker: '助理', text: GREETING }])
  const [input, setInput] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  const [statusText, setStatusText] = useState('')
  const transcriptRef = useRef<HTMLDivElement>(null)

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
      setMessages((prev) => [...prev, { speaker: '助理', text: turn.reply_text }])
      setResults(turn.results)
      setSelectedIndex(null)
      setStatusText(`花費 $${turn.cost_usd.toFixed(4)}`)
    },
    onError: (err: Error) => {
      setMessages((prev) => [...prev, { speaker: '助理', text: `處理時發生錯誤：${err.message}` }])
      setStatusText('發生錯誤')
    },
  })

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const message = input.trim()
    if (!message || conversationId === null || sendMutation.isPending) return
    setMessages((prev) => [...prev, { speaker: '你', text: message }])
    setInput('')
    setStatusText('思考中…')
    sendMutation.mutate(message)
  }

  const selected = selectedIndex !== null ? results[selectedIndex] : null

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex h-3/5 flex-col rounded-lg border border-border bg-card p-4">
        <div ref={transcriptRef} className="min-h-0 flex-1 space-y-3 overflow-auto">
          {messages.map((m, i) => (
            <p key={i} className="text-sm">
              <span className={m.speaker === '你' ? 'font-bold text-text-primary' : 'text-text-secondary'}>{m.speaker}：</span>
              <span className={m.speaker === '你' ? 'text-text-primary' : 'text-text-secondary'}>{m.text}</span>
            </p>
          ))}
        </div>
        <form onSubmit={onSubmit} className="mt-3 flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={conversationId === null || sendMutation.isPending}
            className="flex-1 rounded border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={conversationId === null || sendMutation.isPending}
            className="rounded bg-primary px-4 py-2 text-sm font-bold text-white disabled:opacity-40"
          >
            送出
          </button>
        </form>
        {statusText && <p className="mt-1 text-sm text-text-secondary">{statusText}</p>}
      </div>

      <div className="flex min-h-0 flex-1 gap-4">
        <div className="flex w-3/5 flex-col rounded-lg border border-border bg-card p-4">
          <h2 className="mb-3 text-base font-bold">這一輪的相關片段</h2>
          <div className="min-h-0 flex-1 overflow-auto">
            {results.length === 0 ? (
              <EmptyState title="尚無結果" hints={['在上方輸入想找的內容開始對話']} />
            ) : (
              <table className="w-full text-left text-sm">
                <thead className="sticky top-0 bg-[#F0F2F5] text-xs text-text-secondary">
                  <tr>
                    <th className="px-2 py-2">編號</th>
                    <th className="px-2 py-2">影片名稱</th>
                    <th className="px-2 py-2">時間範圍</th>
                    <th className="px-2 py-2">相似度</th>
                    <th className="px-2 py-2">融合分數</th>
                    <th className="px-2 py-2">命中來源</th>
                    <th className="px-2 py-2">片段描述</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r, index) => (
                    <tr
                      key={r.segment_id}
                      onClick={() => setSelectedIndex(index)}
                      className={`cursor-pointer border-b border-border last:border-0 ${
                        index === selectedIndex ? 'bg-row-selected' : 'hover:bg-app-bg'
                      }`}
                    >
                      <td className="px-2 py-2">{index + 1}</td>
                      <td className="px-2 py-2">{r.video_title}</td>
                      <td className="px-2 py-2">{formatTimeRange(r.start_sec, r.end_sec)}</td>
                      <td className="px-2 py-2">{formatPercent(r.similarity)}</td>
                      <td className="px-2 py-2">{r.fusion_score.toFixed(3)}</td>
                      <td className="px-2 py-2">{r.hit_source}</td>
                      <td className="px-2 py-2">{truncate(r.description, 80)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="w-2/5 overflow-auto rounded-lg border border-border bg-card p-4">
          {selected ? (
            <video
              key={selected.segment_id}
              src={getStreamUrl(selected.video_id)}
              controls
              className="w-full rounded bg-black"
              onLoadedMetadata={(e) => {
                e.currentTarget.currentTime = selected.start_sec
                e.currentTarget.play().catch(() => {})
              }}
            />
          ) : (
            <EmptyState title="點選左方片段即可播放" />
          )}
        </div>
      </div>
    </div>
  )
}
