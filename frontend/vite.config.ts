import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

const BACKEND = 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), vueDevTools(), tailwindcss()],
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
      '/health': { target: BACKEND, changeOrigin: true },
      '/ws': { target: BACKEND, changeOrigin: true, ws: true },
    },
  },
})
