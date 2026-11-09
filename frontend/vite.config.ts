import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发时通过 /api 代理到 FastAPI 后端
// 注：本机 8000 已被其他容器占用，后端默认改到 8001
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
})
