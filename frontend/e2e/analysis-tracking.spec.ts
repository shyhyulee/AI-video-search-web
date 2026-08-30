import { expect, test, type Page } from '@playwright/test'

/** 「影片與分析」頁的分析追蹤狀態機。
 *
 * smoke.spec.ts 對這頁只驗到「清單載得進來」「沒勾選時開始分析是停用的」就
 * 停了——真的按下去會呼叫 OpenAI，每跑一次測試付一次錢。但按下去之後那一整
 * 段（送出 → 追蹤 job → 每秒輪詢 → 到終態跳通知 → 刷新清單）正是
 * lib/useAnalysisQueue.ts 的全部內容，沒有東西看著它。
 *
 * 所以把後端整個攔下來（`page.route()`）：`POST /analyze` 根本不會送到後端，
 * 不會有任何分析真的啟動、不會花錢，但走的是元件真正的程式碼路徑，而且
 * queued → running → completed 的節奏由測試餵，不用等真的分析跑完。
 */

const VIDEO = {
  id: 901,
  title: '被攔截的待分析影片',
  source: 'youtube',
  source_url: 'https://www.youtube.com/watch?v=stub901',
  duration_sec: 300,
  status: 'pending',
  pipeline_stage: null,
  created_at: '2026-08-30T09:00:00',
  analyzed_at: null,
  segment_count: null,
  cost_usd: null,
  summary: null,
  document_type: null,
  has_transcript: false,
  has_visual: false,
  has_ocr: false,
}

const JOB_ID = 500

function analysisJob(status: string, extra: Record<string, unknown> = {}) {
  return {
    id: JOB_ID,
    job_type: 'analysis',
    video_id: VIDEO.id,
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
  }
}

const json = (body: unknown, status = 200) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify(body),
})

/** 攔下這一頁會用到的三支 API。`jobStatuses` 是 job 輪詢依序要回的狀態，
 * 最後一個會一直重複回（模擬「到終態就不再變」）。 */
async function stubAnalysis(
  page: Page,
  options: { activeJobs?: unknown[]; jobStatuses?: ReturnType<typeof analysisJob>[] } = {},
) {
  const { activeJobs = [], jobStatuses = [] } = options

  await page.route(
    (url) => url.pathname.endsWith('/api/v1/videos') && url.searchParams.get('status') === 'pending',
    (route) => route.fulfill(json([VIDEO])),
  )
  await page.route(
    (url) => url.pathname.endsWith('/api/v1/jobs') && url.searchParams.get('active') === 'true',
    (route) => route.fulfill(json(activeJobs)),
  )
  await page.route(`**/api/v1/videos/${VIDEO.id}/analyze`, (route) =>
    route.fulfill(json(analysisJob('queued'), 202)),
  )
  let call = 0
  await page.route(`**/api/v1/jobs/${JOB_ID}`, (route) => {
    const next = jobStatuses[Math.min(call, jobStatuses.length - 1)]
    call += 1
    return route.fulfill(json(next))
  })
}

test('送出分析後一路追到完成，通知只跳一次', async ({ page }) => {
  await stubAnalysis(page, {
    jobStatuses: [
      analysisJob('running', { stage: '場景切分中', progress_percent: 20 }),
      analysisJob('completed', { cost_usd: 0.12, completed_at: '2026-08-30T09:01:00' }),
    ],
  })
  await page.goto('/videos')
  await expect(page.getByText(VIDEO.title)).toBeVisible()

  await page.getByRole('checkbox', { name: `選取 ${VIDEO.title}` }).check()
  await page.getByRole('button', { name: '開始分析' }).click()

  // 追蹤接上之後，那一列的狀態要跟著 job 走
  await expect(page.getByText('場景切分中')).toBeVisible()
  await expect(page.getByText('✓ 分析完成')).toBeVisible()

  // 送出去的影片要取消勾選，否則「移除」還亮著，一按就把分析中的影片刪掉
  await expect(page.getByText(/已選 0 \/ 5/)).toBeVisible()

  // 完成通知只跳一則：輪詢會把 completed 讀到很多次，去重壞掉就會疊出好幾則
  await expect(page.getByText(`「${VIDEO.title}」分析完成，已移到影片庫`)).toHaveCount(1)
  await page.waitForTimeout(2500)
  await expect(page.getByText(`「${VIDEO.title}」分析完成，已移到影片庫`)).toHaveCount(1)
})

test('分析失敗時顯示錯誤與重試鈕', async ({ page }) => {
  await stubAnalysis(page, {
    jobStatuses: [
      analysisJob('running'),
      analysisJob('failed', { error_message: '這是假的分析失敗訊息' }),
    ],
  })
  await page.goto('/videos')

  await page.getByRole('checkbox', { name: `選取 ${VIDEO.title}` }).check()
  await page.getByRole('button', { name: '開始分析' }).click()

  // 錯誤訊息出現兩次是對的，各有各的用途，所以分開斷言而不是用 .first() 帶過：
  // 清單那一列留著原因（toast 會自己消失），toast 則是當下的通知。
  await expect(page.getByText('分析失敗', { exact: true })).toBeVisible()
  await expect(page.getByText('這是假的分析失敗訊息', { exact: true })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText(
    `「${VIDEO.title}」分析失敗：這是假的分析失敗訊息`,
  )
  await expect(page.getByRole('button', { name: '重試' })).toBeVisible()
})

test('重新整理後靠 active jobs 把進行中的分析接回來', async ({ page }) => {
  // 這條路徑不經過「按下開始分析」：追蹤清單只活在 React state，F5 之後是空的，
  // 全靠 GET /jobs?active=true 把工作撈回來。壞掉的話畫面會停在「等待分析」，
  // 使用者看不到任何進度。
  await stubAnalysis(page, {
    activeJobs: [analysisJob('running', { stage: '畫面分析 40%' })],
    jobStatuses: [analysisJob('running', { stage: '畫面分析 40%' })],
  })

  await page.goto('/videos')

  // 完全沒有互動，狀態就該自己接上
  await expect(page.getByText('畫面分析 40%')).toBeVisible()
  await expect(page.getByText('等待分析')).toHaveCount(0)
})
