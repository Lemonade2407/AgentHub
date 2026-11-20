import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发时通过 /api 代理到 FastAPI 后端。
// - host: 0.0.0.0 同时覆盖 localhost / 127.0.0.1，避免 IPv6-only 监听导致打不开；
// - proxy target 固定 127.0.0.1，避免 localhost 解析到 ::1 而后端只监听 IPv4。
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
})
