import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // 后端代理目标默认 :8000；本机端口被占时在 frontend/.env.local 设 API_PROXY_TARGET 覆盖（不入库）。
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.API_PROXY_TARGET || 'http://127.0.0.1:8000'
  return {
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
        '/api': apiTarget,
      },
    },
  }
})
