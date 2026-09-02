import fs from 'node:fs'
import path from 'node:path'
import { expect, test, type Page, type Route } from '@playwright/test'

/** 「片段搜尋」頁的結果選取與播放。
 *
 * 送出搜尋會呼叫 OpenAI（embedding ＋ 可能的翻譯），所以 `POST /search` 用
 * `page.route()` 攔下來回假結果——測的是前端「搜完之後怎麼選、怎麼播」的狀態機。
 * 串流一樣換成 4KB 的 WebM fixture 並自己處理 Range，理由見 conversation.spec.ts。
 *
 * 這頁原本只有兩支 smoke（空狀態、空白查詢不送出），**選取與播放零覆蓋**——
 * 而那正是第五輪要跟 AI對話 頁合併成同一份 hook 的東西。
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

const TWO_HITS = {
  results: [result(11, FIRST_START, '第一個片段的畫面描述'), result(12, SECOND_START, '第二個片段的畫面描述')],
  cost_usd: 0.0001,
  is_confident: true,
}

async function stubBackend(page: Page, { response = TWO_HITS }: { response?: unknown } = {}) {
  const sent: unknown[] = []
  const clip = fs.readFileSync(path.join(test.info().project.testDir, 'fixtures', 'tiny.webm'))

  await page.route('**/api/v1/search', (route: Route) => {
    sent.push(route.request().postDataJSON())
    return route.fulfill({ json: response })
  })
  await page.route(`**/api/v1/videos/${VIDEO_ID}/stream`, (route: Route) => {
    const range = route.request().headers()['range']
    const headers = { 'content-type': 'video/webm', 'accept-ranges': 'bytes' }
    if (!range) return route.fulfill({ status: 200, headers, body: clip })
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
const runSearch = async (page: Page, text: string) => {
  await page.getByPlaceholder('描述想尋找的事件').fill(text)
  await page.getByRole('button', { name: '搜尋' }).click()
}

test.describe('片段搜尋的結果選取', () => {
  test('搜完自動選第一名，畫面停在該時間點且不播', async ({ page }) => {
    await stubBackend(page)
    await page.goto('/search')
    await runSearch(page, '晶片工廠')

    await expect(page.getByText(/找到 2 個相關片段/)).toBeVisible()
    await expect(player(page)).toBeVisible()
    await expect
      .poll(() => player(page).evaluate((el: HTMLVideoElement) => Math.round(el.currentTime)))
      .toBe(FIRST_START)
    expect(await player(page).evaluate((el: HTMLVideoElement) => el.paused)).toBe(true)
  })

  test('使用者自己點結果才播', async ({ page }) => {
    await stubBackend(page)
    await page.goto('/search')
    await runSearch(page, '晶片工廠')
    await expect(player(page)).toBeVisible()

    await page.getByText('第二個片段的畫面描述').click()

    await expect
      .poll(() => player(page).evaluate((el: HTMLVideoElement) => el.paused), { timeout: 5000 })
      .toBe(false)
    expect(
      await player(page).evaluate((el: HTMLVideoElement) => el.currentTime),
    ).toBeGreaterThanOrEqual(SECOND_START)
  })

  test('搜過但沒找到時，右側講的是「沒有找到」而不是「尚未選取」', async ({ page }) => {
    await stubBackend(page, { response: { results: [], cost_usd: 0.0001, is_confident: false } })
    await page.goto('/search')
    await runSearch(page, 'zzz 不存在的東西')

    await expect(page.getByText('沒有找到相關片段')).toBeVisible()
    await expect(player(page)).toHaveCount(0)
    // 搜尋前那句提示必須換掉——「搜尋後這裡會顯示片段與播放器」在搜過之後就不對了
    await expect(page.getByText('搜尋後這裡會顯示片段與播放器')).toHaveCount(0)
  })

  test('送出時把搜尋範圍一起帶上（沒勾選就送 null）', async ({ page }) => {
    const sent = await stubBackend(page)
    await page.goto('/search')
    await runSearch(page, '晶片工廠')
    await expect(page.getByText(/找到 2 個相關片段/)).toBeVisible()

    expect(sent).toEqual([{ query: '晶片工廠', video_ids: null }])
  })
})
