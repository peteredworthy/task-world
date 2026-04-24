import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import type { IncomingMessage, ServerResponse } from 'node:http'
import type { Socket } from 'node:net'

// Override the backend port via VITE_API_PORT env var.
// Example (isolated dev server on port 9100):
//   cd ui && VITE_API_PORT=9100 npm run dev -- --port 9173
const apiPort = process.env.VITE_API_PORT ?? '8000'
const httpTarget = `http://localhost:${apiPort}`
const wsTarget = `ws://localhost:${apiPort}`

function isServerResponse(value: ServerResponse | Socket): value is ServerResponse {
  return 'writeHead' in value
}

function isSocket(value: ServerResponse | Socket): value is Socket {
  return 'destroy' in value
}

function swallowProxyError(
  _err: Error,
  req: IncomingMessage,
  resOrSocket: ServerResponse | Socket,
) {
  // Backend reloads briefly break in-flight connections. Keep the Vite dev
  // server alive and let the browser-side retry logic recover.
  if (isServerResponse(resOrSocket)) {
    const res = resOrSocket
    if (!res.headersSent) {
      res.writeHead(502, { 'Content-Type': 'text/plain' })
    }
    if (!res.writableEnded) {
      res.end(`Upstream temporarily unavailable: ${req.url ?? ''}`)
    }
    return
  }

  if (isSocket(resOrSocket) && !resOrSocket.destroyed) {
    resOrSocket.destroy()
  }
}

function withProxyErrorHandling(target: string, ws = false) {
  return {
    target,
    changeOrigin: true,
    ws,
    configure: (proxy: {
      on: (
        event: 'error',
        handler: (
          err: Error,
          req: IncomingMessage,
          resOrSocket: ServerResponse | Socket,
        ) => void,
      ) => void
    }) => {
      proxy.on('error', swallowProxyError)
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': withProxyErrorHandling(httpTarget),
      '/ws': withProxyErrorHandling(wsTarget, true),
      '/mcp': withProxyErrorHandling(httpTarget),
      '/health': withProxyErrorHandling(httpTarget),
      '/docs': withProxyErrorHandling(httpTarget),
    },
  },
})
