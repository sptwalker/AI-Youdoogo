import '@ant-design/v5-patch-for-react-19'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { RouterProvider } from 'react-router-dom'
import { ApiError } from './api/http'
import { router } from './router'
import './index.css'

// API 错误已由拦截器提示；未被调用方接住时仍留下诊断信息。
window.addEventListener('unhandledrejection', (e) => {
  if (e.reason instanceof ApiError) {
    console.error('未处理的 API 请求失败', e.reason)
    e.preventDefault()
  }
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: '#3f7565' } }}>
      <RouterProvider router={router} />
    </ConfigProvider>
  </StrictMode>,
)
