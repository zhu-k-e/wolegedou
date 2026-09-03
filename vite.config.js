import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: './',  // 相对路径构建，dist 可直接双击 index.html 打开（file:// 兼容）
  plugins: [react()],
  server: {
    port: 5176,
    strictPort: true,
    // 后端地址可经环境变量覆盖（默认 8000），方便评委自定义端口或本机多实例
    proxy: {
      '/api': {
        target: process.env.BACKEND_URL || 'http://localhost:8000',
        changeOrigin: true,
        timeout: 180000,
        proxyTimeout: 180000
      },
      '/health': {
        target: process.env.BACKEND_URL || 'http://localhost:8000',
        changeOrigin: true
      },
      '/ws': {
        target: process.env.BACKEND_URL || 'http://localhost:8000',
        changeOrigin: true,
        ws: true
      }
    }
  }
})