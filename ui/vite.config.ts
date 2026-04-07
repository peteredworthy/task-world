import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Override the backend port via VITE_API_PORT env var.
// Example (isolated dev server on port 9100):
//   cd ui && VITE_API_PORT=9100 npm run dev -- --port 9173
const apiPort = process.env.VITE_API_PORT ?? '8000'
const httpTarget = `http://localhost:${apiPort}`
const wsTarget = `ws://localhost:${apiPort}`

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: httpTarget,
        changeOrigin: true,
      },
      '/ws': {
        target: wsTarget,
        ws: true,
        on: {
          error: () => {
            // Swallow proxy errors when backend restarts to keep Vite alive
          },
        },
      },
      '/mcp': {
        target: httpTarget,
        changeOrigin: true,
      },
      '/health': {
        target: httpTarget,
        changeOrigin: true,
      },
      '/docs': {
        target: httpTarget,
        changeOrigin: true,
      },
    },
  },
})
