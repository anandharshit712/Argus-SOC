import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API (backend/) is called through /api so the browser needs no CORS setup.
// The target comes from the environment, not from code.
export default defineConfig(({ mode }) => {
  const apiUrl = process.env.VITE_API_URL ?? 'http://localhost:8080'
  return {
    plugins: [react()],
    server: {
      proxy: mode === 'development' ? { '/api': { target: apiUrl, changeOrigin: true } } : undefined,
    },
  }
})
