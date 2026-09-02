import { useState } from 'react'
import type { SearchResult } from '../api/types'

/** 「一批片段結果 → 選中哪一筆 → 播不播」這組狀態，片段搜尋與 AI對話 共用。
 *
 * 兩頁拿到結果的方式不同（一個是按下搜尋、一個是對話回一輪），但拿到之後的規則
 * 完全一樣，而且是**成對**的兩條，分開寫很容易只實作一半：
 *
 * 1. 換上一批新結果 → 自動選第一名，右側直接帶出播放器（docs/05 §8.9）
 * 2. 那次選取**不播**——是程式帶出來的，不是使用者點的，未經指示不該出聲；
 *    使用者自己點某一筆才播（§8.21 把這條補到 AI對話 頁）
 *
 * 抽出來的時機就是第二份出現的時候：§8.21 是把搜尋頁那四行複製到對話頁，
 * 複製當下兩邊就已經是同一段邏輯了。
 */
export function useResultSelection() {
  const [results, setResults] = useState<SearchResult[]>([])
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  // 這次的選取是使用者點的（true，點了就想看）還是程式自動帶出來的預設
  // （false，只把畫面停在該時間點）。
  const [playOnSelect, setPlayOnSelect] = useState(false)

  return {
    results,
    selectedIndex,
    /** 傳給 `VideoPlayer` 的 `autoPlay`。 */
    playOnSelect,
    selected: selectedIndex !== null ? results[selectedIndex] : null,

    /** 換上一批結果：自動選第一名（沒有結果就回到未選取），而且不播。 */
    showResults(list: SearchResult[]) {
      setResults(list)
      setSelectedIndex(list.length > 0 ? 0 : null)
      setPlayOnSelect(false)
    },

    /** 使用者點了第 index 筆：選它，並且播。 */
    pick(index: number) {
      setSelectedIndex(index)
      setPlayOnSelect(true)
    },
  }
}
