import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Dev server proxies /api to the Sentry backend (or tools/mock_sentry.py) on
// :8000, matching architecture §3.1: production is one FastAPI process
// serving both the API and the built SPA on SENTRY_HTTP_PORT.
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 3000,
    proxy: {
      // Overridable so a port clash with another local service cannot silently
      // proxy the dev SPA at an unrelated backend (which looks identical to the
      // API being down, but 404s instead of failing to connect).
      '/api': {
        target: process.env.SENTRY_API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
