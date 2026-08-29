import { defineConfig, devices } from '@playwright/test'

/** e2e smoke 測試的設定。
 *
 * 這不是完整的 e2e 套件，是**重構時的安全網**：前端原本零測試，波 F 要動
 * query key、抽 hook、拆頁面元件，需要一個「改壞了會叫」的東西。所以它只驗
 * 「頁面掛得起來、資料載得進來、互動有反應」，不驗版面細節。
 *
 * 兩件刻意不做的事：
 *
 * 1. **不碰任何會花錢的路徑**——開始分析、整理成文件、對話搜尋送出、語意搜尋
 *    都會呼叫 OpenAI。常態驗證每跑一次就付一次錢是不合理的取捨。YouTube 搜尋
 *    雖然免費但要打外網、會不穩，也排除。
 * 2. **不連正式資料庫**——後端另外起一個連 `avs_test` 的 process（見下面的
 *    webServer），資料由 scripts/seed_smoke_db.py 填成固定的四支影片。連正式庫
 *    的話，你一加影片 smoke 就轉紅，那是資料變了不是程式壞了。
 *
 * port 都刻意避開日常開發用的（後端 8000、Vite 5173），這樣 smoke 可以在你
 * 手邊的 dev server 還開著的時候直接跑。
 */

const API_PORT = 8100
const WEB_PORT = 5273
const BASE_URL = `http://127.0.0.1:${WEB_PORT}`

/** smoke 用的資料庫。預設值跟 docker-compose.yml／.env.example 的本機開發設定
 * 一致，只是資料庫名稱多了 `_test`（密碼是本機固定值、不是機密，見 .env.example）。
 * seed 腳本與後端一定要指向同一個，所以在這裡算一次、兩邊共用。 */
const SMOKE_DSN =
  process.env.TEST_DATABASE_URL ?? 'postgresql://avs:avs_local_dev@localhost:5433/avs_test'

export default defineConfig({
  testDir: './e2e',
  // 全部 smoke 共用同一份唯讀的種子資料，平行跑沒有互相污染的問題。
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? 'list' : [['list'], ['html', { open: 'never' }]],

  use: {
    baseURL: BASE_URL,
    // 失敗時留下 trace 與截圖：這是本機偶爾手動跑的測試，出事時能直接看到
    // 當下畫面比重跑一次快得多。
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },

  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],

  webServer: [
    {
      // 先把測試資料庫填成固定內容，再起後端。`&&` 讓 seed 失敗時後端不會起來，
      // 免得測試對著一個空資料庫跑、失敗訊息指向錯的地方。
      // 後端認的是 DATABASE_URL；db/__init__.py 的 load_dotenv() 不覆寫已存在的
      // 環境變數，所以這裡指定的會蓋過 .env 裡的正式資料庫位址。
      command:
        `cd .. && TEST_DATABASE_URL='${SMOKE_DSN}' uv run python scripts/seed_smoke_db.py && ` +
        `DATABASE_URL='${SMOKE_DSN}' uv run uvicorn ai_video_search_web.api.main:app ` +
        `--host 127.0.0.1 --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/v1/stats`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: `npm run dev -- --port ${WEB_PORT} --strictPort`,
      url: BASE_URL,
      reuseExistingServer: false,
      timeout: 120_000,
      env: { VITE_API_PROXY_TARGET: `http://127.0.0.1:${API_PORT}` },
    },
  ],
})
