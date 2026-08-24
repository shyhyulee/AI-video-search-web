interface ChatBubbleProps {
  speaker: 'user' | 'assistant'
  text: string
}

/** 對話訊息泡泡：使用者靠右＋陶土色底，助理靠左＋暖沙色底，用對齊與底色
 * 區分角色，不只靠文字前綴。 */
export function ChatBubble({ speaker, text }: ChatBubbleProps) {
  const isUser = speaker === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] whitespace-pre-wrap rounded-card px-3.5 py-2 text-sm leading-relaxed ${
          isUser ? 'bg-primary text-white' : 'bg-surface-alt text-text-primary'
        }`}
      >
        {text}
      </div>
    </div>
  )
}
