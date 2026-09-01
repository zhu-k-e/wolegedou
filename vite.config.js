import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: './',  // 相对路径构建，dist 可直接双击 index.html 打开（file:// 兼容）
  plugins: [react()],
  server: {
    port: 5176,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        timeout: 60000,
        proxyTimeout: 60000
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/ws': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true
      }
    }
  }
})