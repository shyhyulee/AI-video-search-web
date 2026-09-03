interface ChatBubbleProps {
  speaker: 'user' | 'assistant'
  text: string
  /** 這則訊息是針對影片某一格畫面的（停格問答），顯示成 `@04:12` 標記。
   *
   * 一定要標出來：同一串對話裡「搜尋整個影片庫」與「問這一格畫面」兩種訊息
   * 長得一樣，回頭看時分不出某個答案是根據哪一格畫面講的。 */
  frameLabel?: string
  /** 點畫面標記時呼叫。**給了才會變成可點的按鈕**：那一格屬於當時選中的影片，
   * 使用者後來換了影片的話，跳過去會是另一支影片的同一秒——所以由呼叫端判斷
   * 現在還指不指得回去，指不回去就別給這個 callback（見 ConversationPage）。 */
  onFrameClick?: () => void
}

/** 對話訊息泡泡：使用者靠右＋陶土色底，助理靠左＋暖沙色底，用對齊與底色
 * 區分角色，不只靠文字前綴。 */
export function ChatBubble({ speaker, text, frameLabel, onFrameClick }: ChatBubbleProps) {
  const isUser = speaker === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] whitespace-pre-wrap rounded-card px-3.5 py-2 text-sm leading-relaxed ${
          isUser ? 'bg-primary text-white' : 'bg-surface-alt text-text-primary'
        }`}
      >
        {frameLabel &&
          (onFrameClick ? (
            <button
              type="button"
              onClick={onFrameClick}
              aria-label={`跳到 ${frameLabel} 的畫面`}
              className={`mb-1 block rounded text-xs font-bold underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${
                isUser ? 'text-white/75 focus-visible:outline-white' : 'text-text-muted focus-visible:outline-primary'
              }`}
            >
              畫面 {frameLabel}
            </button>
          ) : (
            <span
              className={`mb-1 block text-xs font-bold ${isUser ? 'text-white/75' : 'text-text-muted'}`}
            >
              畫面 {frameLabel}
            </span>
          ))}
        {text}
      </div>
    </div>
  )
}
