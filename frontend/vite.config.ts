import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // FastAPI 後端見 src/ai_video_search_web/api/main.py，開發時用
      // uvicorn 跑在 8000（見 docs/09-web-ui-migration-plan.md）。
      //
      // 可以用 VITE_API_PROXY_TARGET 覆寫：e2e smoke 會另外起一個連測試
      // 資料庫的後端（見 playwright.config.ts），不能跟你手邊正在跑的
      // 開發用後端搶同一個 port。預設值不變，一般開發不受影響。
      '/api': process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
    },
  },
})
