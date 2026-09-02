import { expect, test, type Page } from '@playwright/test'

/** 前端 smoke：五個頁籤都掛得起來、資料載得進來、互動有反應。
 *
 * 這是波 F 重構的安全網（前端原本零測試），不是完整的 e2e 套件。斷言刻意寫得
 * 粗——比對的是「清單有沒有東西」「chip 在不在」，不是版面細節，不然改個
 * className 就會轉紅，那樣的測試沒有人會留著。
 *
 * 資料是 scripts/seed_smoke_db.py 填進測試資料庫的固定四支影片，跑之前不用
 * 手動準備任何東西（playwright.config.ts 的 webServer 會自己 seed）。
 * 不碰任何會呼叫 OpenAI 的按鈕，理由見 playwright.config.ts。
 */

const SEEDED = {
  tech: '半導體晶片工廠產線導覽',
  math: '線性代數：向量與矩陣入門',
  failed: '分析失敗的測試影片',
  pending: '還沒分析的測試影片',
  removable: '可移除的測試影片',
}

/** 影片庫清單裡的那一列。
 *
 * 影片標題在影片庫會出現**兩次**（左邊清單列、右邊詳細面板的標題），直接用
 * `getByText(title)` 會撞上 strict mode。清單列是 `role="button"`，詳細面板是
 * `role="heading"`，用角色把兩者分開。
 *
 * 只適用於影片庫：`VideoListItem` 的 role 是 `onClick ? 'button' : undefined`，
 * 而「影片分析」頁沒有詳細面板、不傳 onClick，那裡的列就是普通的 div——
 * 那頁也不會有標題重複的問題，直接用文字定位即可。 */
const row = (page: Page, title: string) => page.getByRole('button', { name: new RegExp(title) })

/** 頂部導覽的頁籤連結。
 *
 * keep-alive 只在**client-side 導航**時成立：`page.goto()` 是整頁重載，React
 * state 一定會沒（第一版就是這樣寫錯的）。要驗 keep-alive 就得真的點頁籤。 */
const tab = (page: Page, label: string) =>
  page.locator('header').getByRole('link', { name: label })

/** 收集這個頁面上的 console error 與未攔截的例外。
 *
 * 白畫面／hook 用錯／query key 打錯這類問題，畫面上不一定看得出來，但一定會在
 * console 留下東西——這是 smoke 抓得到 F1~F5 最可能弄壞的東西的主要手段。
 *
 * 縮圖的 404 要濾掉：種子影片的 file_path 指向不存在的檔案（smoke 不需要真的
 * 影片檔），後端因此回 404，瀏覽器一定會記一筆載入失敗。那是**預期中的**，
 * 濾掉的是這一種而已，不是把所有錯誤都放行。 */
function collectPageErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return
    if (msg.location().url.includes('/thumbnail')) return
    errors.push(`console.error: ${msg.text()}`)
  })
  page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`))
  return errors
}

test.describe('五個頁籤', () => {
  const tabs = [
    { path: '/youtube', name: '新增影片', expect: '搜尋 YouTube' },
    { path: '/videos', name: '影片分析', expect: '待分析影片' },
    { path: '/library', name: '影片庫', expect: '影片庫' },
    { path: '/search', name: '片段搜尋', expect: '搜尋' },
    { path: '/conversation', name: 'AI對話', expect: '這一輪的相關片段' },
  ]

  for (const t of tabs) {
    test(`${t.name} 開得起來且沒有 console error`, async ({ page }) => {
      const errors = collectPageErrors(page)
      await page.goto(t.path)
      await expect(page.getByText(t.expect).first()).toBeVisible()
      expect(errors, `${t.name} 有 console 錯誤`).toEqual([])
    })
  }

  test('未知路徑導回第一個頁籤', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveURL(/\/youtube$/)
  })
})

test.describe('Header 統計', () => {
  test('統計卡有接到 API，不是停在載入中', async ({ page }) => {
    await page.goto('/library')
    await expect(page.getByText('已分析').first()).toBeVisible()
    await expect(page.locator('body')).not.toContainText('載入失敗')
  })
})

test.describe('影片庫', () => {
  test('清單列出種子影片，右側面板帶出第一支的摘要', async ({ page }) => {
    const errors = collectPageErrors(page)
    await page.goto('/library')

    await expect(row(page, SEEDED.tech)).toBeVisible()
    await expect(row(page, SEEDED.math)).toBeVisible()
    await expect(row(page, SEEDED.failed)).toBeVisible()
    // 待分析的影片不該出現在影片庫（它屬於「影片分析」頁）
    await expect(page.getByText(SEEDED.pending)).toHaveCount(0)

    // 預設選第一筆，右側面板要有內容而不是空白
    await expect(page.getByRole('heading', { name: '摘要' })).toBeVisible()
    expect(errors).toEqual([])
  })

  test('主題分類 chips 由標題與摘要推導出來', async ({ page }) => {
    await page.goto('/library')
    // 兩支已分析影片分屬不同分類，見 lib/videoCategory.ts 的關鍵字規則
    await expect(page.getByRole('button', { name: /科技與製造/ })).toBeVisible()
    await expect(page.getByRole('button', { name: /數學與科學/ })).toBeVisible()
  })

  test('庫內搜尋就地篩選，不跳頁也不打搜尋 API', async ({ page }) => {
    await page.goto('/library')
    await expect(row(page, SEEDED.math)).toBeVisible()

    await page.getByLabel('搜尋影片庫').fill('晶片')

    await expect(row(page, SEEDED.tech)).toBeVisible()
    await expect(page.getByText(SEEDED.math)).toHaveCount(0)
    await expect(page).toHaveURL(/\/library$/)
  })

  test('關鍵字沒中時給的是「找不到」而不是空白', async ({ page }) => {
    await page.goto('/library')
    await page.getByLabel('搜尋影片庫').fill('zzzz 不存在的關鍵字')
    await expect(page.getByText(/找不到符合/)).toBeVisible()
  })

  test('狀態篩選切到「分析失敗」只留失敗的那一支', async ({ page }) => {
    await page.goto('/library')
    await page.getByLabel('狀態').selectOption('failed')

    await expect(row(page, SEEDED.failed)).toBeVisible()
    await expect(page.getByText(SEEDED.tech)).toHaveCount(0)
  })

  test('勾選影片會累加到搜尋範圍', async ({ page }) => {
    await page.goto('/library')
    await expect(page.getByText('已選 0 支')).toBeVisible()

    // 只有分析完成的影片可以勾選；失敗那支的 checkbox 是 disabled
    await page.getByRole('checkbox', { disabled: false }).first().check()

    await expect(page.getByText('已選 1 支')).toBeVisible()
  })
})

test.describe('影片與分析', () => {
  test('待分析清單只收還沒產出結果的影片', async ({ page }) => {
    const errors = collectPageErrors(page)
    await page.goto('/videos')

    // 這頁的列沒有 button 語意（見 row() 的說明），用文字定位
    await expect(page.getByText(SEEDED.pending)).toBeVisible()
    // 已分析與分析失敗的都在影片庫，不該出現在這裡
    await expect(page.getByText(SEEDED.tech)).toHaveCount(0)
    await expect(page.getByText(SEEDED.failed)).toHaveCount(0)
    expect(errors).toEqual([])
  })

  test('沒有勾選時「開始分析」是停用的', async ({ page }) => {
    await page.goto('/videos')
    // 這一顆是全站唯一會花錢的觸發點，smoke 只確認停用狀態、絕不按下去
    await expect(page.getByRole('button', { name: '開始分析' })).toBeDisabled()
    await expect(page.getByText(/已選 0 \/ 5/)).toBeVisible()
  })

  test('移除影片後清單與統計卡都跟著更新', async ({ page }) => {
    // 這支是整份 smoke 裡唯一會改資料的，用的是種子資料裡專門的犧牲品。
    //
    // 為什麼非有它不可：把 query key 打錯（例如 ['videos','library'] 寫成
    // ['videos','libraryX']）**不會**讓任何畫面壞掉——react-query 換個 key
    // 還是會呼叫同一個 queryFn，清單照樣載入。真正壞掉的是快取共用與
    // invalidation，而 invalidation 只有在 mutation 之後才看得出來。刪除是
    // 全站唯一不呼叫 OpenAI 的 mutation，所以它是 smoke 唯一構得到的入口。
    await page.goto('/videos')
    await expect(page.getByText(SEEDED.removable)).toBeVisible()

    const beforeCount = await page.getByText(/待分析影片（\d+）/).textContent()

    await page.getByRole('checkbox', { name: `選取 ${SEEDED.removable}` }).check()
    await page.getByRole('button', { name: '移除' }).click()
    // 確認對話框裡也有一顆「移除」，要指名是對話框裡的那一顆
    await page.getByRole('dialog').getByRole('button', { name: '移除' }).click()

    await expect(page.getByText(SEEDED.removable)).toHaveCount(0)
    // 標題上的數字來自同一份 ['videos','pending'] 快取，invalidation 沒接對就不會變
    await expect(page.getByText(/待分析影片（\d+）/)).not.toHaveText(beforeCount ?? '')
  })
})

test.describe('搜尋影片', () => {
  test('未搜尋時顯示空狀態，不會自己發出查詢', async ({ page }) => {
    const errors = collectPageErrors(page)
    await page.goto('/search')

    await expect(page.getByText('輸入描述以搜尋影片內容')).toBeVisible()
    await expect(page.getByText('搜尋後這裡會顯示片段與播放器')).toBeVisible()
    expect(errors).toEqual([])
  })

  test('空白查詢不會送出（不花錢）', async ({ page }) => {
    await page.goto('/search')
    await page.getByRole('button', { name: '搜尋' }).click()
    await expect(page.getByText('請輸入想搜尋的內容')).toBeVisible()
  })
})

test.describe('頁籤 keep-alive', () => {
  test('切走再切回來，庫內搜尋的關鍵字還在', async ({ page }) => {
    await page.goto('/library')
    await page.getByLabel('搜尋影片庫').fill('晶片')
    await expect(page.getByText(SEEDED.math)).toHaveCount(0)

    await tab(page, '片段搜尋').click()
    await expect(page.getByText('輸入描述以搜尋影片內容')).toBeVisible()

    await tab(page, '影片庫').click()
    // keep-alive（App.tsx 的 KeepAlivePage）保住頁面 state，關鍵字不該被清掉
    await expect(page.getByLabel('搜尋影片庫')).toHaveValue('晶片')
  })
})
