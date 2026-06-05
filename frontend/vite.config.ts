import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

const BACKEND = 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  plugins: [
    vue(),
    command === 'serve' ? vueDevTools() : null,
    tailwindcss(),
  ].filter(Boolean),
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: {
      '/chat': { target: BACKEND, changeOrigin: true },
      '/sessions': { target: BACKEND, changeOrigin: true },
      '/capabilities': { target: BACKEND, changeOrigin: true },
      '/agent-types': { target: BACKEND, changeOrigin: true },
      '/skills': { target: BACKEND, changeOrigin: true },
      '/mcp': { target: BACKEND, changeOrigin: true },
      '/health': { target: BACKEND, changeOrigin: true },
      '/metrics': { target: BACKEND, changeOrigin: true },
      '/alerts': { target: BACKEND, changeOrigin: true },
      '/browser': { target: BACKEND, changeOrigin: true },
      '/ws': { target: BACKEND, changeOrigin: true, ws: true },
    },
  },
}))
