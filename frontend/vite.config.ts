import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: 'antd-date-picker',
              test: /node_modules[\\/]rc-picker[\\/]/,
              includeDependenciesRecursively: false,
            },
            {
              name: 'ant-design-pro',
              test: /node_modules[\\/]@ant-design[\\/]pro-/,
              includeDependenciesRecursively: false,
            },
          ],
        },
      },
    },
  },
  server: {
    proxy: {
      // 本地开发代理到 FastAPI 后端
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
