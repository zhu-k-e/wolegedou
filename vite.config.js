import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5176,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'https://stations-timer-estimate-philip.trycloudflare.com',
        changeOrigin: true,
        timeout: 60000,
        proxyTimeout: 60000
      },
      '/health': {
        target: 'https://stations-timer-estimate-philip.trycloudflare.com',
        changeOrigin: true
      },
      '/ws': {
        target: 'https://stations-timer-estimate-philip.trycloudflare.com',
        changeOrigin: true,
        ws: true
      }
    }
  }
})