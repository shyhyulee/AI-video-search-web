import { expect, test, type Page } from '@playwright/test'

/** 影片庫右側的詳細面板。
 *
 * smoke.spec.ts 對它只驗到「有摘要標題、不是空白」。面板上三顆按鈕裡有兩顆
 * （整理成文件、重新分析）會呼叫 OpenAI，所以 smoke 不碰——但那兩顆的收尾
 * 邏輯正是面板裡最複雜的部分。這裡把後端攔下來（`page.route()`），按下去的
 * 請求根本不會送到後端，不會花錢，走的卻是元件真正的程式碼路徑。
 *
 * 種子資料見 scripts/seed_smoke_db.py。
 */

const TECH = '半導體晶片工廠產線導覽'
const MATH = '線性代數：向量與矩陣入門'
const FAILED = '分析失敗的測試影片'

const row = (page: Page, title: string) => page.getByRole('button', { name: new RegExp(title) })
const panelTitle = (page: Page, title: string) => page.getByRole('heading', { name: title })

/** 開影片庫並明確選一支。
 *
 * 不靠「預設會選第一筆」：清單預設按 analyzed_at 排序，而種子資料是同一秒寫
 * 進去的，誰排第一不保證——第一版測試就是賭了這個，四支同時紅。 */
async function selectVideo(page: Page, title: string) {
  await page.goto('/library')
  await row(page, title).click()
  await expect(panelTitle(page, title)).toBeVisible()
}

const json = (body: unknown, status = 200) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify(body),
})

const DOCUMENT = {
  doc_type: 'sop',
  title: '半導體產線 SOP',
  overview: '這是攔截器造出來的概述，會被寫回影片摘要。',
  sections: [
    {
      heading: '第一階段：晶圓進料',
      steps: [
        // 秒數刻意落在種子樣本影片（30 秒）之內，這樣「點時間戳跳到該時間點」
        // 才驗得到真的有 seek，見 scripts/seed_smoke_db.py 的 _ensure_sample_video()
        { timestamp_sec: 12, heading: '確認晶圓批號', detail: '核對批號與工單是否相符。' },
        { timestamp_sec: 24, heading: '送進光刻機', detail: '確認光罩對位。' },
      ],
    },
  ],
  uncovered: ['影片沒有交代無塵室的更衣程序'],
}

test('面板帶出選中影片的標題、分類與摘要', async ({ page }) => {
  await selectVideo(page, TECH)

  // exact 才分得開：主題 chip 是 <button>，文字是「科技與製造」加上數量，
  // 只有面板上的 Badge 的文字剛好等於分類名稱。
  await expect(page.getByText('科技與製造', { exact: true })).toBeVisible()
  await expect(page.getByText(/從晶圓進料、光刻、蝕刻到封裝測試/)).toBeVisible()
})

test('點另一列會整個換過去，不殘留前一支的內容', async ({ page }) => {
  await selectVideo(page, TECH)

  await row(page, MATH).click()

  await expect(panelTitle(page, MATH)).toBeVisible()
  await expect(panelTitle(page, TECH)).toHaveCount(0)
  await expect(page.getByText(/矩陣乘法的運算規則/)).toBeVisible()
})

test('分析失敗的影片：兩顆會花錢的按鈕都停用，並說明原因', async ({ page }) => {
  await selectVideo(page, FAILED)

  await expect(page.getByRole('button', { name: '在此影片內搜尋' })).toBeDisabled()
  await expect(page.getByRole('button', { name: '整理成文件' })).toBeDisabled()
  await expect(page.getByText('這支影片分析失敗，沒有片段可以產生摘要。')).toBeVisible()
  await expect(page.getByText('這支影片分析失敗，沒有片段可以整理成文件。')).toBeVisible()
})

test('整理成文件：顯示等待狀態，完成後把文件排出來', async ({ page }) => {
  let documentCalls = 0
  await page.route('**/api/v1/videos/*/document', async (route) => {
    documentCalls += 1
    // 這支端點是同步的、真的會等 LLM，所以刻意延遲一下，讓等待狀態看得到
    await new Promise((resolve) => setTimeout(resolve, 300))
    return route.fulfill(json({ video_id: 1, document: DOCUMENT, model: 'gpt-4o-mini' }))
  })

  await selectVideo(page, TECH)

  await page.getByRole('button', { name: '整理成文件' }).click()

  await expect(page.getByText(/整理中…會一併更新摘要/)).toBeVisible()
  await expect(page.getByText('✓ 文件與摘要已更新')).toBeVisible()

  // 文件內容真的排出來了
  await expect(page.getByText('第一階段：晶圓進料')).toBeVisible()
  await expect(page.getByText('確認晶圓批號')).toBeVisible()
  await expect(page.getByText('影片未涵蓋的部分')).toBeVisible()
  // overview 刻意不重印——它就是上面那段摘要，印兩次是這次合併要消掉的重複
  await expect(page.getByText(DOCUMENT.overview)).toHaveCount(0)

  expect(documentCalls, '只該送出一次').toBe(1)
})

test('整理成文件失敗時，把錯誤講出來而不是靜靜地什麼都沒發生', async ({ page }) => {
  await page.route('**/api/v1/videos/*/document', (route) =>
    route.fulfill(json({ error: { code: 'INTERNAL', message: '模型沒有回傳可用的文件內容', details: null } }, 500)),
  )

  await selectVideo(page, TECH)
  await page.getByRole('button', { name: '整理成文件' }).click()

  await expect(page.getByText(/整理失敗：/)).toBeVisible()
})

test('重新整理後靠 active jobs 把重新分析的進度接回來', async ({ page }) => {
  // 這條路徑不經過按鈕：`reanalysisJobId` 只活在 React state，F5 之後是空的，
  // 全靠 GET /jobs?active=true 撈回來。壞掉的話面板完全不顯示進度，而按鈕
  // 卻因為影片 status 是 analyzing 而停用——使用者看到一個卡住的畫面。
  //
  // 對每一支種子影片都回一個工作，這樣測試不必假設哪一支是哪個 id。
  const activeJobFor = (videoId: number) => ({
    id: 700 + videoId,
    job_type: 'analysis',
    video_id: videoId,
    status: 'running',
    stage: '建立向量中',
    progress_percent: null,
    progress_message: null,
    error_message: null,
    cost_usd: null,
    created_at: '2026-08-30T09:00:00',
    started_at: '2026-08-30T09:00:01',
    completed_at: null,
  })

  await page.route(
    (url) => url.pathname.endsWith('/api/v1/jobs') && url.searchParams.get('active') === 'true',
    (route) => route.fulfill(json([1, 2, 3, 4, 5].map(activeJobFor))),
  )
  await page.route(/\/api\/v1\/jobs\/(\d+)$/, (route) => {
    const jobId = Number(new URL(route.request().url()).pathname.split('/').pop())
    return route.fulfill(json(activeJobFor(jobId - 700)))
  })

  await selectVideo(page, TECH)

  // 完全沒有互動，進度就該自己接上
  await expect(page.getByText(/重新分析中…建立向量中/)).toBeVisible()
})

test('重新分析：接上進度，跑完顯示完成', async ({ page }) => {
  const JOB_ID = 610
  const job = (status: string, extra: Record<string, unknown> = {}) => ({
    id: JOB_ID,
    job_type: 'analysis',
    video_id: 1,
    status,
    stage: null,
    progress_percent: null,
    progress_message: null,
    error_message: null,
    cost_usd: null,
    created_at: '2026-08-30T09:00:00',
    started_at: '2026-08-30T09:00:01',
    completed_at: null,
    ...extra,
  })

  await page.route('**/api/v1/videos/*/reanalyze', (route) => route.fulfill(json(job('queued'), 202)))
  let call = 0
  const statuses = [job('running', { stage: '音訊轉錄中' }), job('completed')]
  await page.route(`**/api/v1/jobs/${JOB_ID}`, (route) => {
    const next = statuses[Math.min(call, statuses.length - 1)]
    call += 1
    return route.fulfill(json(next))
  })

  await selectVideo(page, TECH)

  await page.getByRole('button', { name: '重新分析' }).click()

  await expect(page.getByText(/重新分析中…音訊轉錄中/)).toBeVisible()
  await expect(page.getByText('✓ 重新分析完成')).toBeVisible()
  // 這頁刻意不跳 toast，理由見 VideoDetailPanel 裡的說明
  await expect(page.getByRole('alert')).toHaveCount(0)
})


test.describe('點文件時間戳直接播放', () => {
  /** 讓面板出現一份文件。文件是攔截來的，不會呼叫 OpenAI。 */
  async function openDocument(page: Page) {
    await page.route('**/api/v1/videos/*/document', (route) =>
      route.fulfill(json({ video_id: 1, document: DOCUMENT, model: 'gpt-4o-mini' })),
    )
    await selectVideo(page, TECH)
    await page.getByRole('button', { name: '整理成文件' }).click()
    await expect(page.getByText('第一階段：晶圓進料')).toBeVisible()
  }

  test('預設沒有播放器，點了才出現', async ({ page }) => {
    await openDocument(page)

    // 這個面板刻意不常駐播放器（滿版縮圖就是因為吃掉垂直空間被移除的）
    await expect(page.locator('video')).toHaveCount(0)

    await page.getByRole('button', { name: '從 00:12 開始播放：確認晶圓批號' }).click()

    await expect(page.locator('video')).toHaveCount(1)
    await expect(page.getByText('從 00:12 開始播放')).toBeVisible()
  })

  test('真的跳到那個時間點', async ({ page }) => {
    await openDocument(page)
    await page.getByRole('button', { name: '從 00:12 開始播放：確認晶圓批號' }).click()

    const video = page.locator('video')
    // 種子資料的這一支有真的影片檔（30 秒），所以 onLoadedMetadata 會觸發、
    // seek 是真的發生。等 currentTime 追上去，不用固定 sleep。
    await expect
      .poll(() => video.evaluate((el: HTMLVideoElement) => el.currentTime), { timeout: 10_000 })
      .toBeGreaterThan(11)
    const at12 = await video.evaluate((el: HTMLVideoElement) => el.currentTime)
    expect(at12).toBeLessThan(14)
  })

  test('點另一個步驟直接 seek，不重新載入整支影片', async ({ page }) => {
    await openDocument(page)
    await page.getByRole('button', { name: '從 00:12 開始播放：確認晶圓批號' }).click()
    const video = page.locator('video')
    await expect
      .poll(() => video.evaluate((el: HTMLVideoElement) => el.currentTime), { timeout: 10_000 })
      .toBeGreaterThan(11)

    await page.getByRole('button', { name: '從 00:24 開始播放：送進光刻機' }).click()

    await expect
      .poll(() => video.evaluate((el: HTMLVideoElement) => el.currentTime), { timeout: 10_000 })
      .toBeGreaterThan(23)
    // 同一個 <video> 元素、同一個 src——換片段是 seek 不是重載
    await expect(video).toHaveCount(1)
  })

  test('手動拖走之後再點同一個步驟，會回到那個時間點', async ({ page }) => {
    // 這條是 seekKey 存在的理由：秒數沒變的話 effect 不會重跑，少了它這裡會沒反應
    await openDocument(page)
    await page.getByRole('button', { name: '從 00:12 開始播放：確認晶圓批號' }).click()
    const video = page.locator('video')
    await expect
      .poll(() => video.evaluate((el: HTMLVideoElement) => el.currentTime), { timeout: 10_000 })
      .toBeGreaterThan(11)

    await video.evaluate((el: HTMLVideoElement) => {
      el.pause()
      el.currentTime = 2
    })
    await expect.poll(() => video.evaluate((el: HTMLVideoElement) => el.currentTime)).toBeLessThan(5)

    await page.getByRole('button', { name: '從 00:12 開始播放：確認晶圓批號' }).click()

    await expect
      .poll(() => video.evaluate((el: HTMLVideoElement) => el.currentTime), { timeout: 10_000 })
      .toBeGreaterThan(11)
  })

  test('可以關掉播放器，把空間還給步驟', async ({ page }) => {
    await openDocument(page)
    await page.getByRole('button', { name: '從 00:12 開始播放：確認晶圓批號' }).click()
    await expect(page.locator('video')).toHaveCount(1)

    await page.getByRole('button', { name: '關閉播放器' }).click()

    await expect(page.locator('video')).toHaveCount(0)
    await expect(page.getByText('第一階段：晶圓進料')).toBeVisible()
  })
})
