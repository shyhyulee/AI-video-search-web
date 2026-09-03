import { expect, test, type Page } from '@playwright/test'

/** 影片庫左欄清單的排序行為。
 *
 * 清單的其他部分（分類 chips、庫內搜尋、狀態篩選、勾選範圍）已經在 smoke 裡，
 * 但**排序一直沒有任何覆蓋**——欄位與方向都是純資料邏輯，第五輪要把它們搬進
 * `lib/useLibraryList.ts`，所以先在目前的實作上把行為釘住。
 *
 * 種子資料裡進得了影片庫的有三支（見 scripts/seed_smoke_db.py）：
 *
 *   半導體晶片工廠產線導覽   analyzed  cost 0.18
 *   線性代數：向量與矩陣入門  analyzed  cost 0.31
 *   分析失敗的測試影片        failed    cost NULL（排序時當 0）
 *
 * **不驗預設排序**：預設是 analyzed_at 遞減，而種子資料是同一秒寫進去的，
 * 先後不保證（第四輪 F4 踩過這個坑，四支測試同時轉紅）。
 */

const TITLES = { tech: '半導體晶片工廠產線導覽', math: '線性代數：向量與矩陣入門', failed: '分析失敗的測試影片' }
const TITLE_RE = new RegExp(Object.values(TITLES).join('|'))

/** 清單目前由上到下的影片標題。清單列是 role=button（VideoListItem 有 onClick），
 * 用標題正則篩掉分類 chips 與動作列的按鈕。 */
async function order(page: Page): Promise<string[]> {
  const texts = await page.getByRole('button').filter({ hasText: TITLE_RE }).allTextContents()
  return texts.map((t) => Object.values(TITLES).find((title) => t.includes(title)) as string)
}

// exact 是必要的：方向鈕的 aria-label 也含「排序」兩個字，非 exact 會同時命中。
const sortBy = (page: Page, label: string) =>
  page.getByLabel('排序', { exact: true }).selectOption({ label })
const toggleDirection = (page: Page) => page.getByRole('button', { name: /目前為.*排序/ }).click()

test.describe('影片庫排序', () => {
  test('依影片名稱排序，方向鈕把順序反過來', async ({ page }) => {
    await page.goto('/library')
    await expect(page.getByText(TITLES.tech)).toBeVisible()

    await sortBy(page, '影片名稱')
    // 預設是遞減，先切成遞增
    await toggleDirection(page)
    // 中文用字串比較（UTF-16 碼位）：分(U+5206) < 半(U+534A) < 線(U+7DDA)
    expect(await order(page)).toEqual([TITLES.failed, TITLES.tech, TITLES.math])

    await toggleDirection(page)
    expect(await order(page)).toEqual([TITLES.math, TITLES.tech, TITLES.failed])
  })

  test('依片段數與成本排序，沒有值的當 0', async ({ page }) => {
    await page.goto('/library')
    await expect(page.getByText(TITLES.tech)).toBeVisible()

    // **先用名稱排出確定的起點**，理由同下：預設排序是 analyzed_at 遞減，而種子
    // 資料同一秒寫入、順序不保證（第四輪 F4 踩過），拿它當起點的話「片段數一律
    // 當 0」那種壞法會時好時壞地被抓到。
    await sortBy(page, '影片名稱')
    await toggleDirection(page)
    expect(await order(page)).toEqual([TITLES.failed, TITLES.tech, TITLES.math])

    // 片段數：失敗那支是 NULL（當 0）、線代 2、晶片 3
    await sortBy(page, '片段數')
    expect(await order(page)).toEqual([TITLES.failed, TITLES.math, TITLES.tech])

    // 換成成本（0 / 0.18 / 0.31）之後順序必須跟著換。**起點刻意選片段數而不是
    // 名稱**：名稱與成本的遞增順序剛好相同，用它當起點的話「成本一律當 0」這種
    // 壞法會因為 sort 是穩定的而讓順序原封不動，測試就抓不到——實測過。
    await sortBy(page, '成本')
    expect(await order(page)).toEqual([TITLES.failed, TITLES.tech, TITLES.math])

    await toggleDirection(page)
    expect(await order(page)).toEqual([TITLES.math, TITLES.tech, TITLES.failed])
  })

  test('方向鈕的 aria-label 說得出目前是哪個方向', async ({ page }) => {
    await page.goto('/library')
    await expect(page.getByRole('button', { name: '目前為遞減排序，點擊改為遞增' })).toBeVisible()

    await toggleDirection(page)
    await expect(page.getByRole('button', { name: '目前為遞增排序，點擊改為遞減' })).toBeVisible()
  })

  test('排序與庫內搜尋、狀態篩選疊在一起仍然成立', async ({ page }) => {
    await page.goto('/library')
    await page.getByLabel('狀態').selectOption('analyzed')
    await sortBy(page, '影片名稱')
    await toggleDirection(page)

    // 失敗那支被狀態篩掉，剩下兩支照名稱遞增
    expect(await order(page)).toEqual([TITLES.tech, TITLES.math])

    await page.getByLabel('搜尋影片庫').fill('晶片')
    expect(await order(page)).toEqual([TITLES.tech])
  })
})

test.describe('搜尋範圍與勾選是同一份狀態', () => {
  /** 影片庫的 checkbox 就是共用的搜尋範圍本身（§8.25）。以前是兩份狀態單向同步，
   * 在片段搜尋頁清除範圍之後，切回影片庫那些勾選還在。
   *
   * 一定要**點頁籤**切換而不是 page.goto()：goto 是整頁重載，範圍與勾選都會歸零，
   * 那樣測不到 keep-alive 下的分岔（smoke 的 tab() 說明記過同一件事）。 */
  const tab = (page: Page, label: string) =>
    page.locator('header').getByRole('link', { name: label })

  test('在片段搜尋按「清除範圍」，影片庫的勾選跟著取消', async ({ page }) => {
    await page.goto('/library')
    await page.getByRole('checkbox', { disabled: false }).first().check()
    await expect(page.getByText('已選 1 支')).toBeVisible()

    await tab(page, '片段搜尋').click()
    await expect(page.getByText(/搜尋範圍：1 支影片/)).toBeVisible()
    await page.getByRole('button', { name: '清除範圍，改為全部影片' }).click()

    await tab(page, '影片庫').click()
    await expect(page.getByText('已選 0 支')).toBeVisible()
    await expect(page.getByRole('checkbox', { checked: true })).toHaveCount(0)
  })

  test('在片段搜尋移掉 chip，影片庫的那一列也取消勾選', async ({ page }) => {
    await page.goto('/library')
    const boxes = page.getByRole('checkbox', { disabled: false })
    await boxes.nth(0).check()
    await boxes.nth(1).check()
    await expect(page.getByText('已選 2 支')).toBeVisible()

    await tab(page, '片段搜尋').click()
    await page.getByRole('button', { name: /從搜尋範圍移除/ }).first().click()

    await tab(page, '影片庫').click()
    await expect(page.getByText('已選 1 支')).toBeVisible()
    await expect(page.getByRole('checkbox', { checked: true })).toHaveCount(1)
  })

  test('影片庫按「清除選取」，片段搜尋的範圍也跟著清空', async ({ page }) => {
    await page.goto('/library')
    await page.getByRole('checkbox', { disabled: false }).first().check()
    await tab(page, '片段搜尋').click()
    await expect(page.getByText(/搜尋範圍：1 支影片/)).toBeVisible()

    await tab(page, '影片庫').click()
    await page.getByRole('button', { name: '清除選取' }).click()

    await tab(page, '片段搜尋').click()
    await expect(page.getByText(/搜尋範圍：/)).toHaveCount(0)
  })
})
