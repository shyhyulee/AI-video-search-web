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
    {
      // 第二章節純粹是為了把文件撐長：窄螢幕「點時間戳要把播放器捲進視野」那
      // 條，只有在時間戳真的落在畫面外時才驗得到——第一版文件太短，捲不動，
      // 拿掉 scrollIntoView 測試照樣綠。真實文件本來就有 7~20 個步驟。
      heading: '第二階段：蝕刻與檢測',
      steps: [
        { timestamp_sec: 26, heading: '乾式蝕刻', detail: '依製程配方設定氣體比例與時間。' },
        { timestamp_sec: 27, heading: '光阻去除', detail: '以電漿灰化去除殘餘光阻。' },
        { timestamp_sec: 28, heading: '線上量測', detail: '取樣量測關鍵尺寸並回報製程機台。' },
        { timestamp_sec: 29, heading: '缺陷檢視', detail: '自動光學檢測後由工程師複判。' },
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


test.describe('點時間戳進入觀看模式', () => {
  /** 讓面板出現一份文件。文件是攔截來的，不會呼叫 OpenAI。 */
  async function openDocument(page: Page) {
    await page.route('**/api/v1/videos/*/document', (route) =>
      route.fulfill(json({ video_id: 1, document: DOCUMENT, model: 'gpt-4o-mini' })),
    )
    await selectVideo(page, TECH)
    await page.getByRole('button', { name: '整理成文件' }).click()
    await expect(page.getByText('第一階段：晶圓進料')).toBeVisible()
  }

  /** 等播放器把影片載進來並跳到目標秒數。用 poll 而不是固定 sleep。 */
  async function expectSeekedTo(page: Page, sec: number) {
    const video = page.locator('video')
    await expect
      .poll(() => video.evaluate((el: HTMLVideoElement) => el.currentTime), { timeout: 10_000 })
      .toBeGreaterThan(sec - 1)
    expect(await video.evaluate((el: HTMLVideoElement) => el.currentTime)).toBeLessThan(sec + 3)
  }

  test('清單版面沒有播放器，點時間戳才切進觀看模式', async ({ page }) => {
    await openDocument(page)

    // 摘要上方原本那塊播放器已經移除，清單版面完全沒有 <video>
    await expect(page.locator('video')).toHaveCount(0)
    await expect(page.getByLabel('搜尋影片庫')).toBeVisible()

    await page.getByRole('button', { name: '從 00:12 開始播放：確認晶圓批號' }).click()

    // 影片庫的清單收起來，換成觀看版面
    await expect(page.locator('video')).toHaveCount(1)
    await expect(page.getByRole('button', { name: '返回影片庫' })).toBeVisible()
    await expect(page.getByLabel('搜尋影片庫')).toHaveCount(0)
  })

  test('觀看模式右邊仍然看得到摘要與文件', async ({ page }) => {
    await openDocument(page)
    await page.getByRole('button', { name: '從 00:12 開始播放：確認晶圓批號' }).click()

    await expect(page.getByRole('heading', { name: '摘要' })).toBeVisible()
    await expect(page.getByText(/從晶圓進料、光刻、蝕刻到封裝測試/)).toBeVisible()
    await expect(page.getByText('第一階段：晶圓進料')).toBeVisible()
    // 管理動作留在影片庫，觀看時不該出現
    await expect(page.getByRole('button', { name: '整理成文件' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '重新分析' })).toHaveCount(0)
  })

  test('真的跳到點的那個時間點', async ({ page }) => {
    await openDocument(page)
    await page.getByRole('button', { name: '從 00:12 開始播放：確認晶圓批號' }).click()
    // 種子資料的這一支有真的影片檔（30 秒），seek 是真的發生
    await expectSeekedTo(page, 12)
  })

  test('在觀看模式裡點另一個步驟直接 seek，不重新載入', async ({ page }) => {
    await openDocument(page)
    await page.getByRole('button', { name: '從 00:12 開始播放：確認晶圓批號' }).click()
    await expectSeekedTo(page, 12)
    const srcBefore = await page.locator('video').evaluate((el: HTMLVideoElement) => el.currentSrc)

    // 這是這個版面存在的理由：邊看邊跳下一步，不用退回清單
    await page.getByRole('button', { name: '從 00:24 開始播放：送進光刻機' }).click()

    await expectSeekedTo(page, 24)
    expect(await page.locator('video').evaluate((el: HTMLVideoElement) => el.currentSrc)).toBe(srcBefore)
  })

  test('手動拖走之後再點同一個步驟，會回到那個時間點', async ({ page }) => {
    // 這條是 seekKey 存在的理由：秒數沒變的話 effect 不會重跑
    await openDocument(page)
    await page.getByRole('button', { name: '從 00:12 開始播放：確認晶圓批號' }).click()
    await expectSeekedTo(page, 12)

    await page.locator('video').evaluate((el: HTMLVideoElement) => {
      el.pause()
      el.currentTime = 2
    })
    await expect
      .poll(() => page.locator('video').evaluate((el: HTMLVideoElement) => el.currentTime))
      .toBeLessThan(5)

    await page.getByRole('button', { name: '從 00:12 開始播放：確認晶圓批號' }).click()

    await expectSeekedTo(page, 12)
  })

  test('窄螢幕點時間戳時，播放器會捲進視野', async ({ page }) => {
    // <md 是上下堆疊：時間戳在下方的文件裡，點了之後影片會在畫面外的上方開始
    // 播——聽得到卻看不到。實跑 390px 才發現的，所以留一支測試看著。
    await page.setViewportSize({ width: 390, height: 844 })
    await openDocument(page)
    // 點文件最下面那個步驟：Playwright 會先把它捲進視野，播放器因此被推出畫面
    // 外——這正是要驗的情境。
    await page.getByRole('button', { name: '從 00:29 開始播放：缺陷檢視' }).click()
    await expectSeekedTo(page, 29)

    await expect
      .poll(async () =>
        page.locator('video').evaluate((el: HTMLVideoElement) => {
          const r = el.getBoundingClientRect()
          return r.top >= -5 && r.bottom <= window.innerHeight + 5
        }),
      )
      .toBe(true)
  })

  test('返回影片庫回到清單，播放器消失', async ({ page }) => {
    await openDocument(page)
    await page.getByRole('button', { name: '從 00:12 開始播放：確認晶圓批號' }).click()
    await expect(page.locator('video')).toHaveCount(1)

    await page.getByRole('button', { name: '返回影片庫' }).click()

    await expect(page.locator('video')).toHaveCount(0)
    await expect(page.getByLabel('搜尋影片庫')).toBeVisible()
    await expect(panelTitle(page, TECH)).toBeVisible()
  })
})


test.describe('超出影片長度的時間戳不給點', () => {
  /** 種子影片是 30 秒（見 scripts/seed_smoke_db.py），所以 02:00 這一步一定
   * 對不上——這正是實測 8 支真實文件裡 3 支會出現的情況：模型寫出影片裡根本
   * 沒有的時間點（最誇張的是 18:33 的影片寫出 22:56 的步驟）。 */
  const DOC_WITH_BAD_STEP = {
    ...DOCUMENT,
    sections: [
      {
        heading: '第一階段：晶圓進料',
        steps: [
          { timestamp_sec: 12, heading: '確認晶圓批號', detail: '核對批號與工單是否相符。' },
          { timestamp_sec: 120, heading: '這一步的時間點不存在', detail: '模型編出來的步驟。' },
        ],
      },
    ],
  }

  async function openDocument(page: Page) {
    await page.route('**/api/v1/videos/*/document', (route) =>
      route.fulfill(json({ video_id: 1, document: DOC_WITH_BAD_STEP, model: 'gpt-4o-mini' })),
    )
    await selectVideo(page, TECH)
    await page.getByRole('button', { name: '整理成文件' }).click()
    await expect(page.getByText('第一階段：晶圓進料')).toBeVisible()
  }

  test('對不上的時間戳停用，範圍內的照常可點', async ({ page }) => {
    await openDocument(page)

    await expect(
      page.getByRole('button', { name: '從 00:12 開始播放：確認晶圓批號' }),
    ).toBeEnabled()
    await expect(
      page.getByRole('button', { name: '02:00：超出影片長度，無法播放' }),
    ).toBeDisabled()
  })

  test('用一句話講出來，不是只靠 tooltip', async ({ page }) => {
    await openDocument(page)

    // 只有 title 的話，等於只有已經起疑的人才會發現
    await expect(page.getByText(/有 1 個步驟的時間點超出影片長度（00:30）/)).toBeVisible()
    await expect(page.getByText(/已停用它們的播放連結/)).toBeVisible()
  })

  test('點停用的時間戳不會進觀看模式', async ({ page }) => {
    await openDocument(page)

    // force 略過 Playwright 的可互動性檢查，模擬使用者硬點下去
    await page.getByRole('button', { name: '02:00：超出影片長度，無法播放' }).click({ force: true })

    await expect(page.locator('video')).toHaveCount(0)
    await expect(page.getByLabel('搜尋影片庫')).toBeVisible()
  })

  test('沒有超出長度的文件不會出現那句提示', async ({ page }) => {
    await page.route('**/api/v1/videos/*/document', (route) =>
      route.fulfill(json({ video_id: 1, document: DOCUMENT, model: 'gpt-4o-mini' })),
    )
    await selectVideo(page, TECH)
    await page.getByRole('button', { name: '整理成文件' }).click()
    await expect(page.getByText('第一階段：晶圓進料')).toBeVisible()

    await expect(page.getByText(/超出影片長度/)).toHaveCount(0)
  })
})
