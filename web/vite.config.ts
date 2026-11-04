import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // The simulation service (inference/server.py) runs on 8000 in development; it also renders the archive.
  server: { proxy: { '/api': 'http://127.0.0.1:8000', '/answers': 'http://127.0.0.1:8000',
    '/how-it-works': 'http://127.0.0.1:8000', '/stats': 'http://127.0.0.1:8000' } },
})
