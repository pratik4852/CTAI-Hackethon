import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API base is injected at build time so the same bundle can be pointed at a
// local backend, a container on the same host, or a separate deployment.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: mode !== 'production',
    chunkSizeWarningLimit: 900,
  },
}))
