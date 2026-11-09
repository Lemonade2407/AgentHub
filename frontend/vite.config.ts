import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

<<<<<<< HEAD
// 开发时通过 /api 代理到 FastAPI 后端（默认端口 8000）
=======
// 开发时通过 /api 代理到 FastAPI 后端
// 注：本机 8000 已被其他容器占用，后端默认改到 8001
>>>>>>> 47840490efc0088f6d22732094d9c57c7571fb6e
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
<<<<<<< HEAD
        target: 'http://localhost:8000',
=======
        target: 'http://localhost:8001',
>>>>>>> 47840490efc0088f6d22732094d9c57c7571fb6e
        changeOrigin: true,
      },
    },
  },
})
