import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发时通过 /api 代理到 FastAPI 后端（默认端口 8000）
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
