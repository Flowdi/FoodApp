import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const appName = process.env.APP_NAME || env.APP_NAME || 'Vorrat'
  const shortcutIcon = { src: '/icon-192.png', sizes: '192x192', type: 'image/png' }

  return {
    define: { __APP_NAME__: JSON.stringify(appName) },
    plugins: [
      vue(),
      VitePWA({
        registerType: 'autoUpdate',
        manifest: {
          id: '/',
          name: appName,
          short_name: appName,
          description: 'Lebensmittel gemeinsam verwalten',
          lang: 'de',
          theme_color: '#173b2d',
          background_color: '#f5f2e9',
          display: 'standalone',
          start_url: '/',
          scope: '/',
          icons: [
            { src: '/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
            { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
            { src: '/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
            { src: '/icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' }
          ],
          shortcuts: [
            { name: 'Sprechen', short_name: 'Sprechen', description: 'Sprachbefehl aufnehmen', url: '/voice', icons: [shortcutIcon] },
            { name: 'Einkaufsliste', short_name: 'Einkauf', description: 'Einkaufsliste öffnen', url: '/?mode=shopping', icons: [shortcutIcon] },
            { name: 'Kassenbon scannen', short_name: 'Kassenbon', description: 'Kassenbon erfassen', url: '/?mode=receipt', icons: [shortcutIcon] },
            { name: 'Bestand', short_name: 'Bestand', description: 'Vorrat anzeigen', url: '/?mode=stock', icons: [shortcutIcon] }
          ]
        },
        workbox: { importScripts: ['/push-handler.js'], navigateFallback: '/index.html', runtimeCaching: [{ urlPattern: /^\/api\//, handler: 'NetworkOnly' }] }
      })
    ],
    server: { proxy: { '/api': 'http://127.0.0.1:8000' } }
  }
})
