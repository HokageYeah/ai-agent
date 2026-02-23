import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// NOTE: 配置 Vite 开发服务器和代理
// 后端服务运行在 localhost:8002
export default defineConfig({
  plugins: [vue()],
  resolve: {
    // 路径别名：@ 指向 src 目录，方便组件引用
    // 使用 ESM 兼容写法（import.meta.url）替代 CommonJS 的 __dirname
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,         // 前端开发服务器端口
    open: true,         // 启动后自动打开浏览器
    proxy: {
      // 反向代理：将 /api 路径转发到后端服务，避免跨域问题
      '/api': {
        target: 'http://127.0.0.1:8002',
        changeOrigin: true,
        rewrite: (path) => path,  // 保持路径不变
      },
    },
  },
})
