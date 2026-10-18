import { fileURLToPath, URL } from 'node:url'

import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vite.dev/config/
export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [
      vue(),
      command === 'serve' && vueDevTools(), // dev server only, never in the production build
    ],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      // Dev only: forward /api calls to the backend so the browser sees one origin (no CORS)
      proxy: {
        '/api': {
          target: env.BACKEND_URL || 'http://localhost:8000',
          changeOrigin: true,
          // Token for a shared backend (its API_TOKEN), so the browser never needs it
          headers: env.BACKEND_TOKEN ? { Authorization: `Bearer ${env.BACKEND_TOKEN}` } : {},
        },
      },
    },
  }
})
