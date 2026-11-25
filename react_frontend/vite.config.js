import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    hmr: { timeout: 60000, overlay: false },
    proxy: {
      '/api': {
        target:       'http://127.0.0.1:8001',
        changeOrigin: true,
        rewrite:      path => path.replace(/^\/api/, ''),
        timeout:      60000,
        proxyTimeout: 60000,
        configure: (proxy) => {
          proxy.on('error', (err, _req, res) => {
            if (err.code === 'ECONNREFUSED') {
              // Destroy socket so axios .catch() fires → frontend retry loop runs
              try { res.destroy() } catch {}
              return
            }
            console.error('[proxy error]', err.message)
          })
        },
      },
    }
  }
})