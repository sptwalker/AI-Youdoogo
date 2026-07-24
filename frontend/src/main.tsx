import '@ant-design/v5-patch-for-react-19'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { RouterProvider } from 'react-router-dom'
import { ApiError } from './api/client'
import { router } from './router'
import './index.css'

// API 错误已由拦截器 message.error 提示过；抑制其 unhandledrejection 控制台噪音，
// 非 API 的真实异常仍照常冒泡（便于排查）。
window.addEventListener('unhandledrejection', (e) => {
  if (e.reason instanceof ApiError) e.preventDefault()
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider locale={zhCN}>
      <RouterProvider router={router} />
    </ConfigProvider>
  </StrictMode>,
)
