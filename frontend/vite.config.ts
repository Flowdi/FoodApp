import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    vue(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'Vorrat – Haushaltsvorräte',
        short_name: 'Vorrat',
        description: 'Lebensmittel gemeinsam verwalten',
        theme_color: '#173b2d',
        background_color: '#f5f2e9',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: '/icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any maskable' }
        ]
      },
      workbox: { navigateFallback: '/index.html', runtimeCaching: [{ urlPattern: /^\/api\//, handler: 'NetworkOnly' }] }
    })
  ],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } }
})
