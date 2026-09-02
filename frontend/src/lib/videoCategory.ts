import type { Video } from '../api/types'

/** 影片主題分類：用關鍵字規則從「標題＋摘要」推導，見
 * docs/05-web-ui-warm-redesign-plan.md §8.17。
 *
 * 刻意**不存進資料庫、也不呼叫 LLM**：分類只吃前端本來就有的兩個欄位
 * （`title`／`summary`），所以整件事就是這一個檔案，加類別或調關鍵字不必動
 * 後端、不必回填既有影片、不花任何 API 成本。
 *
 * 代價寫在 §8.17.6：字典就是天花板，題材差很多的新影片會一路掉進「其他」，
 * 直到有人來補關鍵字。判斷「該補了」的訊號是「其他」那顆 chip 的數量開始
 * 追上其他類別。日後真要換成 AI 分類，把 `classifyVideo()` 換成讀後端回傳的
 * 欄位即可，用到它的 UI 一行都不用改。
 */

/** 固定 10 類。chips 列依這個順序排（只顯示庫裡真的有影片的類別），所以這裡的
 * 順序就是畫面上的順序——「其他」永遠排最後。 */
export const CATEGORY_ORDER = [
  '運動賽事',
  '科技與製造',
  '教學課程',
  '數學與科學',
  '美食料理',
  '旅遊',
  '音樂',
  '新聞時事',
  '人物與娛樂',
  '其他',
] as const

export type VideoCategory = (typeof CATEGORY_ORDER)[number]

/** 一個關鍵字都沒命中時的歸屬。 */
const FALLBACK: VideoCategory = '其他'

/** 關鍵字一律小寫（比對前會把標題與摘要轉小寫），中文沒有大小寫、不受影響。
 *
 * 有幾個簡體字（`工厂`／`制造`）是刻意的：影片庫裡有簡體標題的影片。摘要一律
 * 是 LLM 產的正體中文，所以簡體只影響標題那 3 分，但那正是權重最高的地方。 */
const RULES: Record<Exclude<VideoCategory, typeof FALLBACK>, string[]> = {
  運動賽事: [
    '世界盃', 'fifa', '足球', '梅西', 'messi', '球賽', '棒球', '龍隊', '全場精華',
    '進球', '籃球', 'nba', '中職', '球員', '賽事', '冠軍戰', 'de paul', 'dribbling',
    '球隊', '比賽', '過人',
  ],
  科技與製造: [
    '晶片', 'chip', '半導體', '工廠', '工厂', '主板', '主機板', '技嘉', 'intel',
    '台積電', '生產線', '制造', '製程', 'wafer', 'factory', '顯卡', 'cpu', '板卡',
    '電子產品', '製造',
  ],
  教學課程: [
    'python', '程式', '教學', '入門', '新手', '安裝', 'code', '開發', 'javascript',
    '零基礎', '課程', 'tutorial', '軟體', 'education', '教育', '學習', '單字', '認識',
  ],
  數學與科學: ['線性代數', '向量', '數學', '微積分', '矩陣', '物理', '化學', '生物', '定理', '公式'],
  美食料理: [
    '壽司', '料理', '食譜', '烹飪', '美食', '做法', '甜點', '餐廳', 'recipe',
    'cooking', 'sushi', '海苔', '米飯',
  ],
  旅遊: ['旅遊', '觀光', '景點', '行程', '一日遊', '遊記', '自由行', 'travel', '地理', '關東', '近畿'],
  音樂: ['mv', '演唱會', '專輯', '樂團', '鋼琴', '吉他', 'music', '歌曲', '音樂'],
  新聞時事: ['新聞', '報導', '快訊', '記者', '選舉', '疫情', '股市', '政府'],
  人物與娛樂: ['最美', 'beautiful faces', '名人', '明星', '排行', '榜單', '訪談', '綜藝', '搞笑', 'vlog', '最美麗'],
}

// 標題命中比摘要命中值錢：標題是人下的、字字都在講主題，摘要是 LLM 產的一整段
// 描述，順帶提到別的領域很常見。
const TITLE_WEIGHT = 3
const SUMMARY_WEIGHT = 1

/** 推導一支影片的主題分類。
 *
 * 用**累計分數取最高**，不是「第一個命中的類別就算」——同時沾到兩類的影片才
 * 判得對。例如《[線性代數] 向量 (Vector)》的摘要有「教學」字樣，但標題命中
 * 「線性代數」「向量」共 6 分，分數把它拉回「數學與科學」。
 */
export function classifyVideo(video: Pick<Video, 'title' | 'summary'>): VideoCategory {
  const title = video.title.toLowerCase()
  const summary = (video.summary ?? '').toLowerCase()

  let best: VideoCategory = FALLBACK
  let bestScore = 0
  for (const [category, keywords] of Object.entries(RULES)) {
    let score = 0
    for (const keyword of keywords) {
      if (title.includes(keyword)) score += TITLE_WEIGHT
      if (summary.includes(keyword)) score += SUMMARY_WEIGHT
    }
    // 嚴格大於：同分時保留先出現的類別，也就是 RULES 的宣告順序決定平手誰贏。
    if (score > bestScore) {
      best = category as VideoCategory
      bestScore = score
    }
  }
  return best
}

/** 影片庫搜尋框的比對：標題或摘要含有這段文字（不分大小寫）。
 *
 * 這是**庫內篩影片**，跟「搜尋影片」頁的語意檢索片段是兩回事——不打任何 API、
 * 不離開頁面，所以沒有違反 §8.6「語意搜尋只有一個入口」的決定，見 §8.17.5。
 */
export function matchesLibraryQuery(video: Pick<Video, 'title' | 'summary'>, query: string): boolean {
  const needle = query.trim().toLowerCase()
  if (needle === '') return true
  return video.title.toLowerCase().includes(needle) || (video.summary ?? '').toLowerCase().includes(needle)
}
