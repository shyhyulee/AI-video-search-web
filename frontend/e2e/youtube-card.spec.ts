import { expect, test, type Page } from '@playwright/test'

/** YouTube 結果卡片的「加入待分析」狀態機。
 *
 * 這一頁在 smoke.spec.ts 裡只驗到空狀態就停了——真的搜尋要打 YouTube、真的
 * 下載要跑 yt-dlp，兩件都會出網路而且會慢會不穩。但卡片裡那段「輪詢 job →
 * 到終態 → 收尾一次」的邏輯，正好是 F2 要動的三處之一，沒有東西看著它。
 *
 * 解法是把後端回應整個攔下來（`page.route()`）：不打 YouTube、不跑 yt-dlp、
 * 不寫資料庫，但走的是元件真正的程式碼路徑。job 的兩次輪詢也由這裡餵，所以
 * 「running → completed」這個轉換是可控的，不用等真的下載。
 */

const ITEM = {
  video_id: 'stub123',
  title: '被攔截的測試影片',
  url: 'https://www.youtube.com/watch?v=stub123',
  description: '這筆結果是測試攔截器造出來的，沒有真的打 YouTube。',
  duration_sec: 754,
  channel: '測試頻道',
  view_count: 12345,
  thumbnail_url: null,
}

const JOB_ID = 4242

function job(status: string, extra: Record<string, unknown> = {}) {
  return {
    id: JOB_ID,
    job_type: 'download',
    video_id: null,
    status,
    stage: null,
    progress_percent: null,
    progress_message: null,
    error_message: null,
    cost_usd: null,
    created_at: '2026-08-30T10:00:00',
    started_at: null,
    completed_at: null,
    ...extra,
  }
}

const json = (body: unknown, status = 200) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify(body),
})

/** 攔下搜尋與下載。`jobStatuses` 是 job 輪詢依序要回的狀態——最後一個會一直
 * 重複回，模擬「到終態之後就不再變」。 */
async function stubYoutube(page: Page, jobStatuses: ReturnType<typeof job>[]) {
  await page.route('**/api/v1/youtube/search**', (route) =>
    route.fulfill(json({ items: [ITEM] })),
  )
  await page.route('**/api/v1/videos/youtube', (route) =>
    route.fulfill(json(job('queued'), 202)),
  )
  let call = 0
  await page.route(`**/api/v1/jobs/${JOB_ID}`, (route) => {
    const next = jobStatuses[Math.min(call, jobStatuses.length - 1)]
    call += 1
    return route.fulfill(json(next))
  })
}

async function search(page: Page) {
  await page.goto('/youtube')
  await page.getByLabel('YouTube 搜尋關鍵字').fill('測試')
  await page.getByRole('button', { name: '搜尋' }).click()
  await expect(page.getByText(ITEM.title)).toBeVisible()
}

test('下載成功後卡片顯示已加入，且只收尾一次', async ({ page }) => {
  // 第一次輪詢還在跑、第二次之後已完成——收尾邏輯只該在轉換那一次動作。
  await stubYoutube(page, [job('running'), job('completed', { video_id: 77 })])
  await search(page)

  await page.getByRole('button', { name: '加入待分析' }).click()

  await expect(page.getByText('✓ 已加入「影片分析」待分析清單')).toBeVisible()
  // 完成通知只跳一則。輪詢會把 completed 讀到很多次，去重壞掉的話會疊出好幾則。
  await expect(page.getByText(`已把「${ITEM.title}」加入待分析清單`)).toHaveCount(1)

  // 再等幾輪輪詢，確認不會又跳一則
  await page.waitForTimeout(2500)
  await expect(page.getByText(`已把「${ITEM.title}」加入待分析清單`)).toHaveCount(1)
})

test('下載失敗時顯示錯誤訊息，不顯示已加入', async ({ page }) => {
  await stubYoutube(page, [
    job('running'),
    job('failed', { error_message: '這是假的下載失敗訊息' }),
  ])
  await search(page)

  await page.getByRole('button', { name: '加入待分析' }).click()

  await expect(page.getByText(/下載失敗：這是假的下載失敗訊息/)).toBeVisible()
  await expect(page.getByText('✓ 已加入「影片分析」待分析清單')).toHaveCount(0)
})

test('影片已經在庫裡時給的是看得懂的話，不是後端原始訊息', async ({ page }) => {
  await page.route('**/api/v1/youtube/search**', (route) =>
    route.fulfill(json({ items: [ITEM] })),
  )
  await page.route('**/api/v1/videos/youtube', (route) =>
    route.fulfill(
      json({ error: { code: 'DUPLICATE_JOB', message: '此影片已經在庫中（狀態：analyzed）', details: null } }, 409),
    ),
  )
  await search(page)

  await page.getByRole('button', { name: '加入待分析' }).click()

  await expect(page.getByText('這支影片已經在影片庫或下載中')).toBeVisible()
  // 後端的原始訊息不該直接漏給使用者
  await expect(page.getByText(/狀態：analyzed/)).toHaveCount(0)
})
