import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The bundle is emitted straight into the Python package so `identitylock serve`
// can hand it to FastAPI's StaticFiles with no copy step and no separate server.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: '../src/identitylock/api/static',
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8420' },
  },
})
