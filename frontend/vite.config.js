import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'

// Publish the module registry as /modules.json so the public landing page uses the SAME list of
// modules as the side panel and Home page (src/config/modules.json is the single source of truth).
const REGISTRY = new URL('./src/config/modules.json', import.meta.url)
const moduleRegistry = () => ({
  name: 'accfino-module-registry',
  generateBundle() { this.emitFile({ type: 'asset', fileName: 'modules.json', source: fs.readFileSync(REGISTRY, 'utf8') }) },
  configureServer(server) {
    server.middlewares.use('/modules.json', (_req, res) => {
      res.setHeader('Content-Type', 'application/json'); res.end(fs.readFileSync(REGISTRY, 'utf8'))
    })
  },
})

export default defineConfig({
  plugins: [react(), moduleRegistry()],
  build: {
    // Vendor code in separate, long-cacheable chunks; route pages are lazy-loaded (see App.jsx)
    rollupOptions: { output: { manualChunks: {
      react:  ['react', 'react-dom', 'react-router-dom'],
      charts: ['recharts'],
      icons:  ['lucide-react'],
    } } },
  },
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