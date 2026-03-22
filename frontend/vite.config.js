import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/parse': 'http://localhost:8000',
      '/enrich': 'http://localhost:8000',
      '/sessions': 'http://localhost:8000',
      '/export': 'http://localhost:8000',
      '/taxonomy': 'http://localhost:8000',
      '/catalog': 'http://localhost:8000',
      '/jobs': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    }
  },
  build: {
    outDir: 'dist'
  }
})
