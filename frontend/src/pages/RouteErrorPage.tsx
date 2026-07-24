import { Button, Result, Space } from 'antd'
import { isRouteErrorResponse, useNavigate, useRouteError } from 'react-router-dom'

function errorDescription(error: unknown): string {
  if (isRouteErrorResponse(error)) {
    return typeof error.data === 'string' ? error.data : `请求失败（${error.status}）`
  }
  if (error instanceof Error) return error.message
  return '页面加载失败，请重试。'
}

export default function RouteErrorPage() {
  const error = useRouteError()
  const navigate = useNavigate()
  return (
    <Result
      status="error"
      title="页面暂时无法打开"
      subTitle={errorDescription(error)}
      extra={(
        <Space>
          <Button type="primary" onClick={() => window.location.reload()}>重新加载</Button>
          <Button onClick={() => navigate('/', { replace: true })}>返回工作桌面</Button>
        </Space>
      )}
    />
  )
}
