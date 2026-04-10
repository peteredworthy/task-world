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
        configure: (proxy) => {
          // Swallow proxy errors on backend restart to keep Vite alive.
          // The `on` property is not processed by Vite — must use `configure`.
          proxy.on('error', () => {})
          proxy.on('proxyReqWs', (_proxyReq, _req, socket) => {
            socket.on('error', () => {})
          })
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
