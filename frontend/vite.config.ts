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
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
