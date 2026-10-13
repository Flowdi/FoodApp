import { createApp } from 'vue'
import { registerSW } from 'virtual:pwa-register'
import App from './App.vue'
import './style.css'

document.title = __APP_NAME__

registerSW({ immediate: true })
createApp(App).mount('#app')
