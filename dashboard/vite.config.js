/* global process */
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The meta CSP needs frame-src for the preview origin (generated apps run on <run-id>.PREVIEW_DOMAIN,
// never in the dashboard origin). Build-time: VITE_PREVIEW_FRAME_SRC="https://*.preview.example.com".
// Unset -> 'self' only, so previews are blocked rather than allowed everywhere.
const previewFrameSrc = (mode) => loadEnv(mode, process.cwd(), 'VITE_').VITE_PREVIEW_FRAME_SRC || ''
const cspFrameSrc = (mode) => ({
  name: 'csp-frame-src',
  transformIndexHtml: (html) => html.replace('__PREVIEW_FRAME_SRC__', previewFrameSrc(mode).replace(/[;'"<>]/g, '')).replace("frame-src 'self' ;", "frame-src 'self';"),
})

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [
    cspFrameSrc(mode),
    react(),
    tailwindcss(),
  ],
  base: '/dashboard/',
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  }
}))
