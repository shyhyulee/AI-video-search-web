import fs from 'node:fs'
import path from 'node:path'
import { expect, test, type Page, type Route } from '@playwright/test'

/** 「AI對話」頁的特徵測試。
 *
 * 這一頁是全站行為最多的（對話生命週期、結果選取與播放、停格問答的模式切換與
 * 上下文、狀態列），但原本只有 smoke 的一支「頁面開得起來」。第五輪重構要動
 * 這一頁之前，先把**現在的行為**釘住。
 *
 * 兩件事被攔下來，理由跟 playwright.config.ts 的原則一致：
 *
 * 1. **對話送出與停格問答都會呼叫 OpenAI**，所以 `POST /conversations`、
 *    `POST /conversations/{id}/messages`、`POST /videos/{id}/frame-qa` 三支
 *    一律用 `page.route()` 回假資料——測的是前端的狀態機，不是後端。
 * 2. **影片串流換成 4KB 的 WebM fixture**。種子資料的 `file_path` 指向不存在的
 *    檔案（見 seed_smoke_db.py），`<video>` 根本載不進來，那樣「定格」與「播放」
 *    兩種狀態都是 `paused === true`，等於驗不到。換成真的能解碼的檔案之後，
 *    `paused`／`currentTime` 才是真的播放器行為。
 */

const VIDEO_ID = 1
const FIRST_START = 12
const SECOND_START = 20

const result = (segmentId: number, startSec: number, description: string) => ({
  segment_id: segmentId,
  video_id: VIDEO_ID,
  video_title: '半導體晶片工廠產線導覽',
  start_sec: startSec,
  end_sec: startSec + 8,
  similarity: 0.42,
  hit_source: 'visual',
  description,
  transcript: null,
  transcript_score: null,
  visual_score: 0.42,
  ocr_score: null,
  fusion_strategy: 'rrf',
  fusion_score: 0.016,
})

const TURN = {
  reply_text: '找到 2 個相關片段。',
  results: [result(11, FIRST_START, '第一個片段的畫面描述'), result(12, SECOND_START, '第二個片段的畫面描述')],
  cost_usd: 0.0002,
  video_ids: [VIDEO_ID],
}

/** 攔掉會花錢的三支端點，並把串流換成 fixture。回傳收到的請求 body 供斷言。 */
async function stubBackend(page: Page, { turn = TURN }: { turn?: unknown } = {}) {
  // fixture 用 testDir 推路徑（絕對路徑），不用 import.meta.url——那會讓 Playwright
  // 改走 ESM loader 載入這個檔案，等於載進第二份 @playwright/test，test.describe()
  // 會註冊不到目前這一輪的 runner 上（實測會直接 "did not expect test.describe()"）。
  const fixture = path.join(test.info().project.testDir, 'fixtures', 'tiny.webm')
  const sent: { messages: unknown[]; frameQA: unknown[] } = { messages: [], frameQA: [] }

  await page.route('**/api/v1/conversations', (route: Route) =>
    route.fulfill({ json: { id: 999 } }),
  )
  await page.route('**/api/v1/conversations/999/messages', (route: Route) => {
    sent.messages.push(route.request().postDataJSON())
    return route.fulfill({ json: turn })
  })
  await page.route(`**/api/v1/videos/${VIDEO_ID}/frame-qa`, (route: Route) => {
    const body = route.request().postDataJSON()
    sent.frameQA.push(body)
    return route.fulfill({
      json: { at_sec: body.at_sec, answer: `畫面裡有 ${sent.frameQA.length} 個人`, cost_usd: 0.0005 },
    })
  })
  // **一定要自己處理 Range**：`route.fulfill({ path })` 只會回 200 整包，Chromium
  // 因此把這段媒體判定成不可 seek（實測 `video.seekable` 是 [0,0]，設 currentTime
  // 直接被忽略、永遠停在 0），播放器「跳到片段起點」那段邏輯就驗不到了。真的後端
  // 用 FastAPI 的 FileResponse，本來就支援 range，這裡只是把同樣的行為補回來。
  const clip = fs.readFileSync(fixture)
  await page.route(`**/api/v1/videos/${VIDEO_ID}/stream`, (route: Route) => {
    const range = route.request().headers()['range']
    const headers = { 'content-type': 'video/webm', 'accept-ranges': 'bytes' }
    if (!range) {
      return route.fulfill({ status: 200, headers, body: clip })
    }
    const [, from, to] = /bytes=(\d*)-(\d*)/.exec(range) ?? []
    const start = Number(from || 0)
    const end = to ? Number(to) : clip.length - 1
    return route.fulfill({
      status: 206,
      headers: { ...headers, 'content-range': `bytes ${start}-${end}/${clip.length}` },
      body: clip.subarray(start, end + 1),
    })
  })
  return sent
}

const player = (page: Page) => page.locator('video')
const send = (page: Page, text: string) =>
  page
    .getByPlaceholder('輸入想找的內容')
    .fill(text)
    .then(() => page.getByRole('button', { name: '送出' }).click())

test.describe('AI對話：一輪對話', () => {
  test('回完自動選第一名，畫面停在該時間點且不播', async ({ page }) => {
    await stubBackend(page)
    await page.goto('/conversation')
    await send(page, '晶片工廠')

    await expect(page.getByText('找到 2 個相關片段。')).toBeVisible()
    // 描述會出現兩次：左欄清單一次、右欄證據面板一次（§8.24 之後右欄跟片段搜尋
    // 一樣有 EvidencePanel），所以要指名第一個。
    await expect(page.getByText('第一個片段的畫面描述').first()).toBeVisible()

    // 自動選第一名：播放器直接出現，不必先點卡片
    await expect(player(page)).toBeVisible()
    await expect
      .poll(() => player(page).evaluate((el: HTMLVideoElement) => Math.round(el.currentTime)))
      .toBe(FIRST_START)
    // **定格**：程式帶出來的選取不出聲
    expect(await player(page).evaluate((el: HTMLVideoElement) => el.paused)).toBe(true)
    await expect(page.getByRole('button', { name: '問這一格（00:12）' })).toBeVisible()
  })

  test('使用者自己點結果才播', async ({ page }) => {
    await stubBackend(page)
    await page.goto('/conversation')
    await send(page, '晶片工廠')
    await expect(player(page)).toBeVisible()

    await page.getByText('第二個片段的畫面描述').click()

    await expect
      .poll(() => player(page).evaluate((el: HTMLVideoElement) => el.paused), { timeout: 5000 })
      .toBe(false)
    expect(
      await player(page).evaluate((el: HTMLVideoElement) => el.currentTime),
    ).toBeGreaterThanOrEqual(SECOND_START)
  })

  test('這一輪沒有結果時不選任何一筆，右側維持空狀態', async ({ page }) => {
    await stubBackend(page, {
      turn: { reply_text: '沒有找到相關片段。', results: [], cost_usd: 0.0002, video_ids: [] },
    })
    await page.goto('/conversation')
    await send(page, '不存在的東西')

    await expect(page.getByText('沒有找到相關片段。')).toBeVisible()
    await expect(page.getByText('尚未選取片段')).toBeVisible()
    await expect(player(page)).toHaveCount(0)
  })

  test('送出時把搜尋範圍一起帶上（沒勾選就送 null）', async ({ page }) => {
    const sent = await stubBackend(page)
    await page.goto('/conversation')
    await send(page, '晶片工廠')
    await expect(page.getByText('找到 2 個相關片段。')).toBeVisible()

    expect(sent.messages).toEqual([{ message: '晶片工廠', video_ids: null }])
  })
})

test.describe('AI對話：停格問答', () => {
  test('切進畫面模式後，同一個輸入框問的是那一格', async ({ page }) => {
    const sent = await stubBackend(page)
    await page.goto('/conversation')
    await send(page, '晶片工廠')
    await expect(player(page)).toBeVisible()

    await page.getByRole('button', { name: '問這一格（00:12）' }).click()
    await expect(page.getByRole('button', { name: '結束畫面提問' })).toBeVisible()
    await expect(page.getByText('針對畫面 00:12 提問')).toBeVisible()

    await page.getByPlaceholder('問這一格畫面').fill('畫面中有幾個人？')
    await page.getByRole('button', { name: '送出' }).click()

    // 問與答兩則泡泡都標著問的是哪一格。exact 是必要的——畫面模式那條提示列
    // 寫的是「針對畫面 00:12 提問」，非 exact 的比對會把它一起算進來。
    await expect(page.getByText('畫面 00:12', { exact: true })).toHaveCount(2)
    await expect(page.getByText('畫面裡有 1 個人')).toBeVisible()
    expect(sent.frameQA).toEqual([
      { at_sec: FIRST_START, question: '畫面中有幾個人？', history: [] },
    ])
    // 這一題不進對話搜尋
    expect(sent.messages).toHaveLength(1)
  })

  test('同一格的追問帶上下文；時間點一變就清空', async ({ page }) => {
    const sent = await stubBackend(page)
    await page.goto('/conversation')
    await send(page, '晶片工廠')
    await expect(player(page)).toBeVisible()

    await page.getByRole('button', { name: '問這一格（00:12）' }).click()
    await page.getByPlaceholder('問這一格畫面').fill('這是什麼地方？')
    await page.getByRole('button', { name: '送出' }).click()
    await expect(page.getByText('畫面裡有 1 個人')).toBeVisible()

    // 同一格追問 → 帶前一輪
    await page.getByPlaceholder('問這一格畫面').fill('那右邊那個呢？')
    await page.getByRole('button', { name: '送出' }).click()
    await expect(page.getByText('畫面裡有 2 個人')).toBeVisible()
    expect(sent.frameQA[1]).toMatchObject({
      at_sec: FIRST_START,
      history: [{ question: '這是什麼地方？', answer: '畫面裡有 1 個人' }],
    })

    // 把播放器拖到別的秒數 → 上下文整串丟掉
    await player(page).evaluate((el: HTMLVideoElement) => {
      el.currentTime = 25
    })
    await expect(page.getByRole('button', { name: '問這一格（00:25）' })).toHaveCount(0)
    await page.getByPlaceholder('問這一格畫面').fill('那這一格呢？')
    await page.getByRole('button', { name: '送出' }).click()
    await expect(page.getByText('畫面裡有 3 個人')).toBeVisible()
    expect(sent.frameQA[2]).toMatchObject({ at_sec: 25, history: [] })
  })
})


test.describe('AI對話：時間戳可點', () => {
  const at = (page: Page) => page.locator('video').evaluate((el: HTMLVideoElement) => Math.round(el.currentTime))
  const paused = (page: Page) => page.locator('video').evaluate((el: HTMLVideoElement) => el.paused)

  test('點證據面板的時間範圍會跳過去並播放，拖走之後再點同一個仍然跳得回去', async ({ page }) => {
    await stubBackend(page)
    await page.goto('/conversation')
    await send(page, '晶片工廠')
    await expect(page.locator('video')).toBeVisible()
    await expect.poll(() => at(page)).toBe(FIRST_START)
    expect(await paused(page)).toBe(true)

    await page.locator('video').evaluate((el: HTMLVideoElement) => {
      el.currentTime = 25
      el.pause()
    })
    await expect.poll(() => at(page)).toBe(25)

    await page.getByRole('button', { name: '從 00:12 開始播放' }).click()
    await expect.poll(() => at(page)).toBe(FIRST_START)
    // 點時間戳是使用者的明確動作，照「使用者點的才播」那條規則要出聲
    await expect.poll(() => paused(page)).toBe(false)

    // **第二次點同一個時間戳**：這一段才是在驗 VideoPlayer 的 seekKey——少了它，
    // startSec 沒變、effect 不重跑，使用者拖走進度之後就再也跳不回去。
    await page.locator('video').evaluate((el: HTMLVideoElement) => {
      el.currentTime = 27
      el.pause()
    })
    await expect.poll(() => at(page)).toBe(27)
    await page.getByRole('button', { name: '從 00:12 開始播放' }).click()
    await expect.poll(() => at(page)).toBe(FIRST_START)
  })

  test('對話泡泡的「畫面 MM:SS」可點，跳回問的那一格', async ({ page }) => {
    await stubBackend(page)
    await page.goto('/conversation')
    await send(page, '晶片工廠')
    await expect(page.locator('video')).toBeVisible()

    await page.locator('video').evaluate((el: HTMLVideoElement) => {
      el.currentTime = 18
    })
    await expect.poll(() => at(page)).toBe(18)
    await page.getByRole('button', { name: /問這一格（00:18）/ }).click()
    await page.getByPlaceholder('問這一格畫面').fill('有幾個人？')
    await page.getByRole('button', { name: '送出' }).click()
    await expect(page.getByText('畫面裡有 1 個人')).toBeVisible()

    await page.locator('video').evaluate((el: HTMLVideoElement) => {
      el.currentTime = 5
    })
    await expect.poll(() => at(page)).toBe(5)
    await page.getByRole('button', { name: '跳到 00:18 的畫面' }).first().click()
    await expect.poll(() => at(page)).toBe(18)
  })
})
